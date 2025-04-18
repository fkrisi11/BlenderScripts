bl_info = {
    "name": "Vertex Group cleaner",
    "author": "Tohru",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Item Tab",
    "description": "Removes all unused vertex groups from selected mesh objects",
    "category": "Object",
}

import bpy

class OBJECT_OT_RemoveUnusedVertexGroups(bpy.types.Operator):
    """Remove all unused vertex groups from selected mesh objects"""
    bl_idname = "object.remove_unused_vertex_groups"
    bl_label = "Remove Unused Vertex Groups"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed_total = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue

            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='OBJECT')

            verts = obj.data.vertices
            used_group_indices = set()
            for v in verts:
                for g in v.groups:
                    used_group_indices.add(g.group)

            to_remove = [vg for vg in obj.vertex_groups if vg.index not in used_group_indices]
            for vg in to_remove:
                obj.vertex_groups.remove(vg)
            removed_total += len(to_remove)

        self.report({'INFO'}, f"Removed {removed_total} unused vertex group(s).")
        return {'FINISHED'}


class VIEW3D_PT_RemoveUnusedVertexGroupsPanel(bpy.types.Panel):
    bl_label = "Vertex Group Cleaner"
    bl_idname = "VIEW3D_PT_remove_unused_vertex_groups"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Item"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Clean Vertex Groups:")
        layout.operator("object.remove_unused_vertex_groups", icon='TRASH')


def register():
    bpy.utils.register_class(OBJECT_OT_RemoveUnusedVertexGroups)
    bpy.utils.register_class(VIEW3D_PT_RemoveUnusedVertexGroupsPanel)


def unregister():
    bpy.utils.unregister_class(OBJECT_OT_RemoveUnusedVertexGroups)
    bpy.utils.unregister_class(VIEW3D_PT_RemoveUnusedVertexGroupsPanel)


if __name__ == "__main__":
    register()
