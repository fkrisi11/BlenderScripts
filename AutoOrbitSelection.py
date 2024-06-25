bl_info = {
    "name": "Auto Orbit Selection",
    "author": "TohruTheDragon",
    "blender": (2, 80, 0),
    "version": (1, 0, 0),
    "location": "3D View > Sidebar > View",
    "description": "Auto-toggles Orbit Selection",
    "category": "3D View",
}

"""
Automatically enables "Orbit Around Selection" when an object is selected.
Disables "Orbit Around Selection" when no objects are selected.

Compatible with:
- Blender 2.x
- Blender 3.x
- Blender 4.x
"""

import bpy

prev_selected_objects = set()
addon_enabled = False

def depsgraph_update(scene, depsgraph):
    global prev_selected_objects

    if not addon_enabled:
        return

    current_selected_objects = {obj.name for obj in scene.objects if obj.select_get()}
    if current_selected_objects != prev_selected_objects:
        if len(current_selected_objects) == 0:
            bpy.context.preferences.inputs.use_rotate_around_active = False
        elif len(current_selected_objects) == 1:
            bpy.context.preferences.inputs.use_rotate_around_active = True
        prev_selected_objects = current_selected_objects

def load_post_handler(dummy):
    check_initial_selection(bpy.context)

def check_initial_selection(context):
    global addon_enabled
    selected_objects = [obj for obj in context.scene.objects if obj.select_get()]
    if addon_enabled and context.scene.auto_orbit:
        if len(selected_objects) > 0:
            bpy.context.preferences.inputs.use_rotate_around_active = True
        else:
            context.preferences.inputs.use_rotate_around_active = False

class VIEW3D_PT_auto_orbit_selection_panel(bpy.types.Panel):
    bl_label = "Auto Orbit Selection"
    bl_idname = "VIEW3D_PT_auto_orbit_selection_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'View'

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "auto_orbit", text="Auto Orbit")
        row = layout.row()
        row.enabled = not context.scene.auto_orbit
        row.prop(context.preferences.inputs, "use_rotate_around_active", text="Orbit Selection")

def register():
    bpy.utils.register_class(VIEW3D_PT_auto_orbit_selection_panel)
    
    bpy.types.Scene.auto_orbit = bpy.props.BoolProperty(
        name="Auto Orbit",
        description="Enable Auto Orbit",
        default=False,
        update=toggle_auto_orbit
    )
    
    bpy.app.handlers.depsgraph_update_post.append(depsgraph_update)
    bpy.app.handlers.load_post.append(load_post_handler)

def unregister():
    bpy.utils.unregister_class(VIEW3D_PT_auto_orbit_selection_panel)
    
    del bpy.types.Scene.auto_orbit
    
    bpy.app.handlers.depsgraph_update_post.remove(depsgraph_update)
    bpy.app.handlers.load_post.remove(load_post_handler)

def toggle_auto_orbit(self, context):
    global addon_enabled
    addon_enabled = context.scene.auto_orbit
    if not addon_enabled:
        context.preferences.inputs.use_rotate_around_active = False
    else:
        check_initial_selection(context)

if __name__ == "__main__":
    register()
