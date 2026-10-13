import bpy
from bpy.props import *

from . import (
    dolphin_rels_to_mod
)

from .hsf import (
    gx_primitive,
    gx_tex,
    hsf_file,
    hsf_creator,
    dxt1lookups,
    io_util,
    bin_mp,
    mesh_utils,
)

from .blender import (
    mesh_utils,
    game_config,
    path_render,
    path_flags,
    path_object,
    scene_export,
    io_util,
    space_file,
    blender_import,
    blender_export,
    hsf_properties,
    hsf_render,
    bone_render,
)

_modules = (
    dolphin_rels_to_mod,

    gx_primitive,
    gx_tex,
    hsf_file,
    hsf_creator,
    dxt1lookups,
    io_util,
    mesh_utils,
    hsf_render,
    bone_render,

    mesh_utils,
    game_config,
    path_render,
    path_flags,
    path_object,
    scene_export,
    io_util,
    space_file,
    bin_mp,
    blender_import,
    blender_export,

    hsf_properties,
)

if "bpy" in locals():
    import importlib
    for m in _modules:
        importlib.reload(m)

bl_info = {
    "name": "Blender Party Board Editor",
    "author": "KillzXGaming",
    "version": (1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Add > Curve > Party Path",
    "description": "Create and load/save mario party paths.",
    "category": "Object",
}

classes = [
    path_object.GameSettings,
    path_object.PartyPathPointProps,

    scene_export.FileItem,
    scene_export.SCENE_OT_add_file,
    scene_export.SCENE_OT_remove_file,

    scene_export.PartyEditorProps,
    
    scene_export.SCENE_OT_folder_select,
    scene_export.SCENE_OT_file_select,
    scene_export.SCENE_OT_build_board,
    scene_export.SCENE_OT_game_boot,
    scene_export.SCENE_OT_save_files,
    scene_export.SCENE_OT_open_map_folder,

    hsf_properties.HSFTextureMapProperties,
    hsf_properties.HSFObjectProperties,
    hsf_properties.HSFLightProperties,
    hsf_properties.HSFCameraProperties,
    hsf_properties.HSFTextureProperties,
    hsf_properties.HSFMaterialProperties,

    hsf_properties.HSF_blender_assign_base_color_textures,

    hsf_render.HsfRenderEngine,
]

classes_ui = [
    
    scene_export.SCENE_UL_file_list,
    scene_export.SCENE_PT_party_editor,

    path_object.OBJECT_OT_add_party_path,
    path_object.OBJECT_PT_party_path,
    path_object.OBJECT_OT_change_edge_direction,
    path_object.OBJECT_OT_import_spaces_mp4to5,
    path_object.OBJECT_OT_import_spaces_mp6to8,
    path_object.OBJECT_OT_export_spaces_mp4to5,
    path_object.OBJECT_OT_export_spaces_mp6to8,

    hsf_properties.HSFObjectPropertiesPanel,

    hsf_properties.HSFMaterialPropertiesPanel,
    hsf_properties.HSFMaterialObjectRenderPropertiesPanel,
    hsf_properties.HSFMaterialRenderPropertiesPanel,
    hsf_properties.HSFMaterialColorPropertiesPanel,
    hsf_properties.HSFMaterialLightingPropertiesPanel,

    hsf_properties.HSFMaterialTextureMapPropertiesPanel,
    hsf_properties.HSFMaterialSamplerPropertiesPanel,

    hsf_properties.MATERIAL_UL_texturemap_list,
    hsf_properties.MATERIAL_UL_add_texturemap,
    hsf_properties.MATERIAL_UL_remove_texturemap,

    hsf_properties.HSF_blender_import,
    hsf_properties.HSF_blender_export,
]

# RenderEngines also need to tell UI Panels that they are compatible with.
# We recommend to enable all panels marked as BLENDER_RENDER, and then
# exclude any panels that are replaced by custom panels registered by the
# render engine, or that are not supported.
def get_panels():
    exclude_panels = {
        "EEVEE_MATERIAL_PT_viewport_settings"
    }
    
    include_panels = {
        'EEVEE_MATERIAL_PT_context_material',
        'MATERIAL_PT_preview'
    }

    panels = []
    for panel in bpy.types.Panel.__subclasses__():
        if hasattr(panel, 'COMPAT_ENGINES'):
            if (('BLENDER_RENDER' in panel.COMPAT_ENGINES and panel.__name__ not in exclude_panels)
                or panel.__name__ in include_panels):
                panels.append(panel)

    return panels

_draw_handler = None

def add_path_drawer():
    global _draw_handler
    if _draw_handler is None:
        _draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            path_render.draw_path, (), 'WINDOW', 'POST_VIEW')
        bpy.app.handlers.depsgraph_update_post.append(_force_redraw)

def remove_path_drawer():
    global _draw_handler
    if _draw_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, 'WINDOW')
        _draw_handler = None
        if _force_redraw in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_force_redraw)

def _force_redraw(args):
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

def menu_func(self, context):
    self.layout.operator(path_object.OBJECT_OT_add_party_path.bl_idname,
                         text="Party Path",
                         icon='CURVE_BEZCURVE')

def menu_func_import_spaces_4to5(self, context):
    self.layout.operator(
        path_object.OBJECT_OT_import_spaces_mp4to5.bl_idname,
        text="Party Path MP4-MP5 (.bin)"
    )
def menu_func_import_spaces_6to8(self, context):
    self.layout.operator(
        path_object.OBJECT_OT_import_spaces_mp6to8.bl_idname,
        text="Party Path MP6-MP8 (.bin)"
    )

def menu_func_import_hsf(self, context):
    self.layout.operator(
        hsf_properties.HSF_blender_import.bl_idname,
        text="HSF Model (.hsf)"
    )

def menu_func_export_spaces_4to5(self, context):
    self.layout.operator(
        path_object.OBJECT_OT_export_spaces_mp4to5.bl_idname,
        text="Raw Party Path MP4-MP5 (.bin)"
    )

def menu_func_export_spaces_6to8(self, context):
    self.layout.operator(
        path_object.OBJECT_OT_export_spaces_mp6to8.bl_idname,
        text="Raw Party Path MP6-MP8 (.bin)"
    )

def menu_func_export_hsf(self, context):
    self.layout.operator(
        hsf_properties.HSF_blender_export.bl_idname,
        text="HSF Model (.hsf)"
    )

def after_register():
    print(f"after_register")
    path_object.load_game_list()
    return None

def register():
    for c in classes_ui:
        bpy.utils.register_class(c)

    # order is important. We need ui dynamic properties done  first before game ui material gets registered
    path_object.register_dynamic_properties()

    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.VIEW3D_MT_curve_add.append(menu_func)
    add_path_drawer()

    bpy.types.Mesh.party_properties = bpy.props.PointerProperty(type=path_object.PartyPathPointProps)

    bpy.types.Scene.party_properties = bpy.props.PointerProperty(type=scene_export.PartyEditorProps)

    bpy.types.Object.hsf_obj_properties = PointerProperty(type=hsf_properties.HSFObjectProperties)
    bpy.types.Object.hsf_light_properties = PointerProperty(type=hsf_properties.HSFLightProperties)
    bpy.types.Object.hsf_camera_properties = PointerProperty(type=hsf_properties.HSFCameraProperties)
    bpy.types.Material.hsf_properties = PointerProperty(type=hsf_properties.HSFMaterialProperties)
    bpy.types.Image.hsf_properties = PointerProperty(type=hsf_properties.HSFTextureProperties)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_spaces_4to5)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_spaces_6to8)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_hsf)

    bpy.types.TOPBAR_MT_file_export.append(menu_func_export_spaces_4to5)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export_spaces_6to8)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export_hsf)

    for panel in get_panels():
        panel.COMPAT_ENGINES.add('HSF_RENDER')

    bpy.app.handlers.depsgraph_update_post.append(path_object.depsgraph_update_post)
    bpy.app.timers.register(after_register)

def unregister():
    remove_path_drawer()
    bpy.types.VIEW3D_MT_curve_add.remove(menu_func)

    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_spaces_4to5)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_spaces_6to8)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_spaces_4to5)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_spaces_6to8)

    bpy.types.TOPBAR_MT_file_export.remove(menu_func_import_hsf)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_hsf)

    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    for c in reversed(classes_ui):
        bpy.utils.unregister_class(c)

    for panel in get_panels():
        if 'HSF_RENDER' in panel.COMPAT_ENGINES:
            panel.COMPAT_ENGINES.remove('HSF_RENDER')

    path_object.unregister()

    del bpy.types.Mesh.party_properties
    del bpy.types.Scene.party_properties
    del bpy.types.Object.hsf_obj_properties
    del bpy.types.Object.hsf_light_properties
    del bpy.types.Object.hsf_camera_properties
    del bpy.types.Material.hsf_properties
    del bpy.types.Image.hsf_properties


    if path_object.depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(path_object.depsgraph_update_post)
    bpy.app.timers.unregister(after_register)
