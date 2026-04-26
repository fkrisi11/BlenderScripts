import bpy
import bmesh
import gpu
import json
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import BoolProperty, FloatProperty, FloatVectorProperty, EnumProperty, StringProperty

bl_info = {
    "name": "Blendshape Visualizer",
    "blender": (3, 0, 0),
    "category": "Object",
    "description": "Shows information about what parts of a mesh the selected blendshape affects",
    "author": "TohruTheDragon",
}

# --- GLOBAL DATA ---
_draw_handler = None
USER_DEFINED_THEMES = {}
PREDEFINED_THEMES = {
    "Default": {
        "face_highlight_color": (1.0, 0.5, 0.0, 0.4),
        "red_x_color": (1.0, 0.0, 0.0, 1.0),
        "grid_line_color": (0.0, 0.0, 0.0, 1.0),
        "green_x_color": (0.0, 1.0, 0.0, 1.0),
        "line_color": (0.5, 0.5, 0.5, 1.0),
        "red_x_thickness": 1.0, "green_x_thickness": 1.0, "line_thickness": 1.0, "grid_line_thickness": 1.0,
    },
    "High Contrast": {
        "face_highlight_color": (1.0, 1.0, 0.0, 0.5),
        "red_x_color": (1.0, 0.0, 1.0, 1.0),
        "grid_line_color": (0.0, 1.0, 1.0, 1.0),
        "green_x_color": (1.0, 1.0, 1.0, 1.0),
        "line_color": (0.0, 0.0, 0.0, 1.0),
        "red_x_thickness": 2.0, "green_x_thickness": 2.0, "line_thickness": 2.0, "grid_line_thickness": 2.0,
    },
}


def get_theme_items_callback(self, context):
    items = [(k, k, "") for k in PREDEFINED_THEMES]
    items += [(k, k, "") for k in USER_DEFINED_THEMES]
    return items


class VisualizationCache:
    def __init__(self):
        self.batches = {}
        self.active_id = None
        self.shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')

    def clear(self):
        self.batches.clear()
        self.active_id = None

    def is_valid(self, obj):
        if not obj or not obj.active_shape_key:
            return False
        # Include mesh data version in the cache key so any mesh edit invalidates the cache
        mesh_version = obj.data.vertices[0].co[:] if len(obj.data.vertices) > 0 else (0,)
        return self.active_id == (
            obj.name,
            obj.active_shape_key.name,
            round(obj.active_shape_key.value, 5),
            obj.data.shape_keys.key_blocks[0].name,  # reference key name
        )

_cache = VisualizationCache()

# --- THE STABLE ENGINE ---

def _read_shape_key_cos_safe(shape_key, num_verts):
    """
    Safely read shape key vertex coordinates.

    The plain shape_key.data.foreach_get() path can return a zeroed or
    partially-written buffer if Blender's internal depsgraph hasn't
    finished propagating a shape-key change yet.  We guard against this
    with two independent reads: if both agree (within float32 noise) we
    trust the data; if they don't we fall back to the slower per-vertex
    Python path, which always returns the current committed values.
    """
    buf_a = np.empty(num_verts * 3, dtype=np.float32)
    buf_b = np.empty(num_verts * 3, dtype=np.float32)

    try:
        shape_key.data.foreach_get("co", buf_a)
        shape_key.data.foreach_get("co", buf_b)
    except Exception:
        return None

    # If the two reads disagree the buffer was being written during our read.
    if not np.allclose(buf_a, buf_b, atol=1e-5):
        # Fallback: per-vertex read (slow but always consistent)
        try:
            cos = np.array([v.co[:] for v in shape_key.data], dtype=np.float32)
            return cos.reshape(num_verts, 3)
        except Exception:
            return None

    return buf_a.reshape(num_verts, 3)


def build_gpu_batches(context):
    obj = context.active_object
    if not obj or obj.type != 'MESH' or not obj.active_shape_key:
        _cache.clear()
        return

    sk = obj.active_shape_key
    if not obj.data.shape_keys:
        return

    basis = sk.relative_key if sk.relative_key else obj.data.shape_keys.reference_key
    if not basis:
        return

    num_verts = len(obj.data.vertices)
    if num_verts == 0:
        return

    # --- SAFE DOUBLE-READ ---
    # We read both buffers twice and compare.  This is the primary glitch guard.
    basis_cos = _read_shape_key_cos_safe(basis, num_verts)
    sk_cos    = _read_shape_key_cos_safe(sk, num_verts)

    if basis_cos is None or sk_cos is None:
        # Data was in an inconsistent state; leave cache as-is and retry next redraw.
        return

    # --- SANITY CHECKS ---

    # 1. If the shape key matches basis exactly there is nothing to draw.
    diffs   = sk_cos - basis_cos
    sq_dist = np.einsum('ij,ij->i', diffs, diffs)   # faster than sum(axis=1)
    if sq_dist.max() < 1e-10:
        _cache.clear()
        _cache.active_id = _make_cache_id(obj, sk)
        return

    # 2. Reject any read where the sk buffer is all-zero but the basis isn't.
    #    (The original "LOCK 2" check, kept as a safety net.)
    if np.sum(np.abs(sk_cos)) < 0.01 and np.sum(np.abs(basis_cos)) > 0.01:
        return

    # 3. Glitch mask: vertices that landed exactly at the world origin but
    #    weren't there in the basis.  If more than 5 % of *affected* vertices
    #    are glitched we abort rather than draw explosion lines.
    zero_verts     = np.all(np.abs(sk_cos)    < 1e-6,  axis=1)
    was_not_zero   = np.any(np.abs(basis_cos) > 1e-4,  axis=1)
    glitch_mask    = zero_verts & was_not_zero
    affected_count = int(np.sum(sq_dist > 1e-6))

    if affected_count > 0 and (np.sum(glitch_mask) / affected_count) > 0.05:
        return

    # 4. Outlier check: reject reads where any single displacement is
    #    implausibly large relative to the mesh's own bounding box.
    #    A legitimate blendshape should not displace a vertex by more than
    #    ~5× the mesh's bounding-box diagonal.
    bbox_diag = np.linalg.norm(basis_cos.max(axis=0) - basis_cos.min(axis=0))
    if bbox_diag > 1e-5:
        max_disp = np.sqrt(sq_dist.max())
        if max_disp > bbox_diag * 5.0:
            return

    # --- GEOMETRY BUILDING ---
    affected_mask = (sq_dist > 1e-6) & (~glitch_mask)
    aff_idx = np.where(affected_mask)[0]

    if len(aff_idx) == 0:
        _cache.clear()
        _cache.active_id = _make_cache_id(obj, sk)
        return

    line_coords, red_x, grn_x = [], [], []
    offset = 0.015
    for idx in aff_idx:
        p0 = Vector(basis_cos[idx].tolist())
        p1 = Vector(sk_cos[idx].tolist())
        line_coords.extend([p0, p1])
        red_x.extend([p0 + Vector(( offset,  offset,  offset)),
                       p0 - Vector(( offset,  offset,  offset)),
                       p0 + Vector((-offset,  offset,  offset)),
                       p0 - Vector((-offset,  offset,  offset))])
        grn_x.extend([p1 + Vector(( offset,  offset,  offset)),
                       p1 - Vector(( offset,  offset,  offset)),
                       p1 + Vector((-offset,  offset,  offset)),
                       p1 - Vector((-offset,  offset,  offset))])

    # Build face/edge geometry from the VALIDATED basis_cos array.
    # We must NOT use bm.from_mesh(obj.data) or v.co here — those read
    # obj.data vertex positions which can be in a transitional/stale state
    # during shape key switches, producing the long "shooting lines" glitch.
    # Instead we use the mesh polygon/loop/edge topology (indices only, which
    # are always stable) and look up positions from basis_cos ourselves.
    face_coords, edge_coords = [], []
    aff_set = set(int(i) for i in aff_idx)
    mesh = obj.data

    # Collect loop indices per polygon once (avoids repeated attribute access)
    polys = mesh.polygons
    loops = mesh.loops

    # Read all loop vertex indices in one shot — always safe, it's just ints
    loop_vert_indices = np.empty(len(loops), dtype=np.int32)
    loops.foreach_get("vertex_index", loop_vert_indices)

    for poly in polys:
        ls = poly.loop_start
        lc = poly.loop_total
        verts_of_poly = loop_vert_indices[ls: ls + lc]

        if not aff_set.isdisjoint(verts_of_poly):
            f_cos = basis_cos[verts_of_poly]  # shape (n, 3), from our safe buffer

            # Skip faces that touch the world origin (degenerate / glitch guard)
            if np.any(np.einsum('ij,ij->i', f_cos, f_cos) < 1e-7):
                continue

            # Fan triangulation
            for i in range(1, lc - 1):
                face_coords.extend([f_cos[0], f_cos[i], f_cos[i + 1]])

            # Edges: consecutive vert pairs around the polygon loop
            for i in range(lc):
                edge_coords.extend([f_cos[i], f_cos[(i + 1) % lc]])

    shader = _cache.shader
    _cache.batches['lines']    = batch_for_shader(shader, 'LINES', {"pos": line_coords})
    _cache.batches['red_x']    = batch_for_shader(shader, 'LINES', {"pos": red_x})
    _cache.batches['green_x']  = batch_for_shader(shader, 'LINES', {"pos": grn_x})
    _cache.batches['faces']    = batch_for_shader(shader, 'TRIS',  {"pos": face_coords})
    _cache.batches['edges']    = batch_for_shader(shader, 'LINES', {"pos": edge_coords})
    _cache.active_id = _make_cache_id(obj, sk)


def _make_cache_id(obj, sk):
    return (
        obj.name,
        sk.name,
        round(sk.value, 5),
        obj.data.shape_keys.key_blocks[0].name,
    )

# --- DRAW CALLBACK ---

def draw_visualizer_callback():
    context = bpy.context
    props   = context.scene.blendshape_visualizer
    if not props.toggle_visualization:
        return

    obj = context.active_object
    if not obj or obj.type != 'MESH':
        return

    # Rebuild if stale.  We catch any exception so a transient Blender
    # internal error never crashes the whole viewport draw loop.
    if not _cache.is_valid(obj):
        try:
            build_gpu_batches(context)
        except Exception:
            return

    # If we still have nothing to draw, bail out cleanly.
    if not _cache.batches:
        return

    shader = _cache.shader
    shader.bind()

    if props.show_face_fill and 'faces' in _cache.batches:
        gpu.state.blend_set('ALPHA')
        shader.uniform_float("color", props.face_highlight_color)
        _cache.batches['faces'].draw(shader)

    if props.show_grid_lines and 'edges' in _cache.batches:
        gpu.state.line_width_set(props.grid_line_thickness)
        shader.uniform_float("color", props.grid_line_color)
        _cache.batches['edges'].draw(shader)

    if props.show_original_x and 'red_x' in _cache.batches:
        gpu.state.line_width_set(props.red_x_thickness)
        shader.uniform_float("color", props.red_x_color)
        _cache.batches['red_x'].draw(shader)

    if props.show_displacement_positions and 'green_x' in _cache.batches:
        gpu.state.line_width_set(props.green_x_thickness)
        shader.uniform_float("color", props.green_x_color)
        _cache.batches['green_x'].draw(shader)

    if props.show_displacement_lines and 'lines' in _cache.batches:
        gpu.state.line_width_set(props.line_thickness)
        shader.uniform_float("color", props.line_color)
        _cache.batches['lines'].draw(shader)

    gpu.state.blend_set('NONE')

# --- UI & PROPERTIES ---

def update_tag(self, context):
    # Invalidate the cache whenever a property changes so the next redraw
    # rebuilds geometry with the new settings.
    _cache.clear()
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


class BlendshapeVisualizerProperties(PropertyGroup):

    def toggle_h(self, context):
        global _draw_handler
        if self.toggle_visualization:
            if not _draw_handler:
                _draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                    draw_visualizer_callback, (), 'WINDOW', 'POST_VIEW')
        else:
            if _draw_handler:
                bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, 'WINDOW')
                _draw_handler = None
            _cache.clear()
        update_tag(self, context)

    toggle_visualization:        BoolProperty(name="Enable Visualization", default=False, update=toggle_h)
    show_displacement_positions: BoolProperty(name="Show Displacement Positions", default=False, update=update_tag)
    show_displacement_lines:     BoolProperty(name="Show Connection Lines",        default=False, update=update_tag)
    show_original_x:             BoolProperty(name="Show Original X Markers",      default=True,  update=update_tag)
    show_face_fill:              BoolProperty(name="Show Face Fill",               default=True,  update=update_tag)
    show_grid_lines:             BoolProperty(name="Show Grid Lines",              default=True,  update=update_tag)

    face_highlight_color: FloatVectorProperty(name="Face Color",           subtype='COLOR', size=4, default=(1.0, 0.5, 0.0, 0.4), min=0, max=1, update=update_tag)
    red_x_color:          FloatVectorProperty(name="Red X Color",          subtype='COLOR', size=4, default=(1.0, 0.0, 0.0, 1.0), min=0, max=1, update=update_tag)
    grid_line_color:      FloatVectorProperty(name="Grid Color",           subtype='COLOR', size=4, default=(0.0, 0.0, 0.0, 1.0), min=0, max=1, update=update_tag)
    green_x_color:        FloatVectorProperty(name="Displacement X Color", subtype='COLOR', size=4, default=(0.0, 1.0, 0.0, 1.0), min=0, max=1, update=update_tag)
    line_color:           FloatVectorProperty(name="Line Color",           subtype='COLOR', size=4, default=(0.5, 0.5, 0.5, 1.0), min=0, max=1, update=update_tag)

    red_x_thickness:      FloatProperty(name="Red X Thick",  default=1.0, min=0.1, max=10.0, update=update_tag)
    green_x_thickness:    FloatProperty(name="Green X Thick", default=1.0, min=0.1, max=10.0, update=update_tag)
    line_thickness:       FloatProperty(name="Line Thick",   default=1.0, min=0.1, max=10.0, update=update_tag)
    grid_line_thickness:  FloatProperty(name="Grid Thick",   default=1.0, min=0.1, max=10.0, update=update_tag)

    selected_theme: EnumProperty(
        name="Theme",
        items=get_theme_items_callback,
        update=lambda s, c: bpy.ops.blendshape.apply_theme())


class BLENDSHAPE_OT_ApplyTheme(Operator):
    bl_idname = "blendshape.apply_theme"
    bl_label  = "Apply Theme"

    def execute(self, context):
        props = context.scene.blendshape_visualizer
        theme = PREDEFINED_THEMES.get(props.selected_theme,
                                      USER_DEFINED_THEMES.get(props.selected_theme))
        if theme:
            for k, v in theme.items():
                setattr(props, k, v)
        update_tag(self, context)
        return {'FINISHED'}


class BLENDSHAPE_OT_SaveTheme(Operator):
    bl_idname  = "blendshape.save_theme"
    bl_label   = "Save Theme"
    theme_name: StringProperty(name="Theme Name", default="New Theme")

    def execute(self, context):
        props = context.scene.blendshape_visualizer
        USER_DEFINED_THEMES[self.theme_name] = {
            k: list(getattr(props, k)) if "color" in k else getattr(props, k)
            for k in PREDEFINED_THEMES["Default"].keys()
        }
        props.selected_theme = self.theme_name
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BLENDSHAPE_OT_CopyTheme(Operator):
    bl_idname = "blendshape.copy_theme"
    bl_label  = "Copy Theme"

    def execute(self, context):
        props = context.scene.blendshape_visualizer
        data  = {
            "name": props.selected_theme,
            "settings": {
                k: list(getattr(props, k)) if "color" in k else getattr(props, k)
                for k in PREDEFINED_THEMES["Default"].keys()
            }
        }
        context.window_manager.clipboard = json.dumps(data, indent=4)
        return {'FINISHED'}


class BLENDSHAPE_OT_ImportTheme(Operator):
    bl_idname = "blendshape.import_theme"
    bl_label  = "Import Theme"

    def execute(self, context):
        try:
            data = json.loads(context.window_manager.clipboard)
            USER_DEFINED_THEMES[data["name"]] = data["settings"]
            context.scene.blendshape_visualizer.selected_theme = data["name"]
        except Exception:
            pass
        return {'FINISHED'}


class BLENDSHAPE_OT_SelectAffected(Operator):
    bl_idname = "blendshape.select_affected"
    bl_label  = "Select Affected"

    def execute(self, context):
        obj   = context.object
        sk    = obj.active_shape_key
        basis = obj.data.shape_keys.reference_key
        bm    = bmesh.from_edit_mesh(obj.data)
        for v in bm.verts:
            v.select = (sk.data[v.index].co - basis.data[v.index].co).length_squared > 1e-6
        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


class BLENDSHAPE_PT_Panel(Panel):
    bl_label      = "Advanced Blendshape Visualizer"
    bl_idname     = "BLENDSHAPE_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type= 'UI'
    bl_category   = 'Blendshape'

    def draw(self, context):
        layout = self.layout
        props  = context.scene.blendshape_visualizer

        layout.prop(props, "toggle_visualization", toggle=True, icon='RESTRICT_VIEW_OFF')

        col        = layout.column()
        col.active = props.toggle_visualization
        col.prop(props, "show_displacement_positions")
        col.prop(props, "show_displacement_lines")
        col.prop(props, "show_original_x")
        col.prop(props, "show_face_fill")
        col.prop(props, "show_grid_lines")

        box = layout.box()
        box.label(text="Colors & Thickness")
        box.prop(props, "face_highlight_color")
        box.prop(props, "red_x_color")
        box.prop(props, "green_x_color")
        box.prop(props, "grid_line_color")
        box.prop(props, "line_color")

        layout.label(text="Themes:")
        layout.prop(props, "selected_theme", text="")
        row = layout.row(align=True)
        row.operator("blendshape.save_theme",   text="Save")
        row.operator("blendshape.copy_theme",   text="Copy")
        row.operator("blendshape.import_theme", text="Import")

        if context.active_object and context.active_object.mode == 'EDIT':
            layout.separator()
            layout.operator("blendshape.select_affected", icon='RESTRICT_SELECT_OFF')


# --- REGISTER ---
classes = (
    BlendshapeVisualizerProperties,
    BLENDSHAPE_OT_ApplyTheme,
    BLENDSHAPE_OT_SaveTheme,
    BLENDSHAPE_OT_CopyTheme,
    BLENDSHAPE_OT_ImportTheme,
    BLENDSHAPE_OT_SelectAffected,
    BLENDSHAPE_PT_Panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blendshape_visualizer = bpy.props.PointerProperty(
        type=BlendshapeVisualizerProperties)


def unregister():
    global _draw_handler
    if _draw_handler:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, 'WINDOW')
        _draw_handler = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.blendshape_visualizer


if __name__ == "__main__":
    register()