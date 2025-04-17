bl_info = {
    "name": "Better Hide",
    "description": "Smart hide / unhide (H) toggle based on current Outliner selection",
    "author": "TohruTheDragon",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "Shortcut: H in Object Mode",
    "category": "Object"
}

import bpy
import time

_last_h_time = 0
_double_press_threshold = 0.3  # seconds

def get_outliner_selected_objects():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'OUTLINER':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        override = {
                            'window': window,
                            'screen': window.screen,
                            'area': area,
                            'region': region
                        }

                        try:
                            if hasattr(bpy.context, "temp_override"):
                                with bpy.context.temp_override(**override):
                                    return [
                                        id for id in bpy.context.selected_ids
                                        if isinstance(id, bpy.types.Object)
                                    ]
                            else:
                                ctx = bpy.context.copy()
                                ctx.update(override)
                                return [
                                    id for id in ctx.get("selected_ids", [])
                                    if isinstance(id, bpy.types.Object)
                                ]
                        except:
                            pass
    return []

class OBJECT_OT_better_hide(bpy.types.Operator):
    bl_idname = "object.better_hide"
    bl_label = "Better Hide Toggle (Per-Object + Double-H)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global _last_h_time

        now = time.time()
        double_press = (now - _last_h_time) < _double_press_threshold
        _last_h_time = now

        selected = get_outliner_selected_objects()

        if not selected:
            self.report({'WARNING'}, "No objects selected.")
            return {'CANCELLED'}

        if double_press:
            # Force-hide all selected
            for obj in selected:
                obj.hide_set(True)
        else:
            # Per-object toggle
            for obj in selected:
                obj.hide_set(not obj.hide_get())

        return {'FINISHED'}

addon_keymaps = []

def register():
    bpy.utils.register_class(OBJECT_OT_better_hide)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        # Register for Object Mode (3D View)
        km_obj = kc.keymaps.new(name='Object Mode', space_type='EMPTY')
        kmi_obj = km_obj.keymap_items.new("object.better_hide", type='H', value='PRESS')
        addon_keymaps.append((km_obj, kmi_obj))

        # Register for Outliner
        km_outliner = kc.keymaps.new(name='Outliner', space_type='OUTLINER')
        kmi_outliner = km_outliner.keymap_items.new("object.better_hide", type='H', value='PRESS')
        addon_keymaps.append((km_outliner, kmi_outliner))

def unregister():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.utils.unregister_class(OBJECT_OT_better_hide)

if __name__ == "__main__":
    register()
