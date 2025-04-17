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
                            with bpy.context.temp_override(**override):
                                return [
                                    id for id in bpy.context.selected_ids
                                    if isinstance(id, bpy.types.Object)
                                ]
                        except:
                            pass
    return []

class OBJECT_OT_better_hide(bpy.types.Operator):
    """Smart H toggle that works even for hidden objects selected in Outliner."""
    bl_idname = "object.better_hide"
    bl_label = "Better Hide Toggle"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = get_outliner_selected_objects()

        if not selected:
            self.report({'WARNING'}, "No objects selected.")
            return {'CANCELLED'}

        any_visible = any(not obj.hide_get() for obj in selected)

        for obj in selected:
            obj.hide_set(any_visible)

        return {'FINISHED'}

addon_keymaps = []

def register():
    bpy.utils.register_class(OBJECT_OT_better_hide)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Object Mode', space_type='EMPTY')
        kmi = km.keymap_items.new("object.better_hide", type='H', value='PRESS')
        addon_keymaps.append((km, kmi))

def unregister():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.utils.unregister_class(OBJECT_OT_better_hide)

if __name__ == "__main__":
    register()