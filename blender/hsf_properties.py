import bpy
import os
from bpy_extras.io_utils import ExportHelper, ImportHelper

from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from . import blender_export
from . import blender_import

from ..hsf import (
    hsf_file,
    bin_mp
)

def set_enum_int(obj, prop_name, prop_int):
    prop = obj.bl_rna.properties[prop_name]
    if prop.type != 'ENUM':
        return

    mapping: Dict[int, str] = {}
    for item in prop.enum_items:
        mapping[int(item.value)] = item.identifier

    if prop_int in mapping:
        setattr(obj, prop_name, mapping[prop_int])

def get_enum_int(obj, prop_name, current_val):
    prop = obj.bl_rna.properties[prop_name]
    if prop.type == 'ENUM':
        integer_id = prop.enum_items[current_val].value
        return integer_id
    return 0

class HSFObjectProperties(bpy.types.PropertyGroup):
    obj_type_items = [
        ('NULL1', 'EMPTY', '', 0),
        ('REPLICA', 'REPLICA', '', 1),
        ('MESH', 'MESH', '', 2),
        ('ROOT', 'ROOT', '', 3),
        ('JOINT', 'JOINT', '', 4),
        ('EFFECT', 'EFFECT', '', 5),
        ('NULL3', 'NULL3', '', 6),
        ('CAMERA', 'CAMERA', '', 7),
        ('LIGHT', 'LIGHT', '', 8),
        ('MAP', 'MAP', '', 9),
    ]
    shape_type_items = [
        ('SINGLE', 'Single Weight', '', 0),
        ('MULTI', 'Multi Weight', '', 2),
    ]

    @staticmethod
    def _enum_items(context):
        objs = context.scene.objects
        items = []
        for i, obj in enumerate(sorted(objs, key=lambda o: o.name)):
            items.append((obj.name, obj.name, f"Object \"{obj.name}\"", "OBJECT_DATA", i))
        if not items:
            items.append(("NONE", "None", "No objects in the scene", "ERROR", 0))
        return items

    def _set_pointer_from_name(self, context):
        name = self.replica_name
        obj = context.scene.objects.get(name)
        self.replica_obj = obj

    def set_replica_obj(self, obj):
        self.replica_obj = obj
        self.replica_name = obj.name

    # The index order that the object is stored in the list
    # This maintains the original order aslong as the user does not delete any of the original obj nodes
    order: bpy.props.IntProperty(default=10000)
    flags: bpy.props.IntProperty(default=0) 
    # type of object
    obj_type: EnumProperty(name="Object Type", items=obj_type_items, default='NULL1')
    # for obj replica type. Can store a copy of the object for a instace rendering like effect
    replica_obj: PointerProperty(name="Replica Object", type=bpy.types.Object)
    # Dropdown for replica object, which should choose the blender objects to set as a copy
    replica_name: EnumProperty(
        name="Replica",
        description="Select an object to use as a replica",
        items=lambda self, ctx: HSFObjectProperties._enum_items(ctx),
        update=lambda self, ctx: self._set_pointer_from_name(ctx),
    )
    # Method for shape blending. Single blends between 2, multi blends up to 32 total.
    shape_type: EnumProperty(name="Shape Morph Type", items=shape_type_items, default='SINGLE')
    base_morph: FloatProperty(name="Base Morph", default=0.0, min=0)

class HSFLightProperties(bpy.types.PropertyGroup):
    light_type_items = [
        ('POINT', 'POINT', '', 0),
        ('SPOT', 'SPOT', '', 1),
        ('INF', 'Infinite', '', 2),
    ]

    target: FloatVectorProperty(name="Target", size=3, min=0, max=2, default=[0, 0, 0])
    color: FloatVectorProperty(name="Color",  subtype='COLOR', size=3, min=0, max=2, default=[1, 1, 1])
    light_type: EnumProperty(name="Type", items=light_type_items, default='INF')

    unk2C: FloatProperty(name="Unk2C", default=0.0)
    ref_distance: FloatProperty(name="Ref Distance", default=0.0)
    ref_brightness: FloatProperty(name="Ref Brightness", default=0.0)
    cutoff: FloatProperty(name="Cutoff", default=0.0)

class HSFCameraProperties(bpy.types.PropertyGroup):
    target: FloatVectorProperty(name="Target", size=3, min=0, max=2, default=[0, 0, 0])
    aspect_dupe: FloatProperty(name="Aspect Dupe", default=0.0)
    fov: FloatProperty(name="Fov", default=0.0)
    near: FloatProperty(name="Near", default=0.0)
    far: FloatProperty(name="Far", default=0.0)

class HSFTextureMapProperties(bpy.types.PropertyGroup):
    wrap_items = [
        ('CLAMP', 'Clamp', '', 0),
        ('REPEAT', 'Repeat', '', 1),
    ]
    filter_items = [
        ('NEAREST', 'Nearest', '', 0),
        ('LINEAR', 'Linear', '', 1)
    ]
    blend_combiner_flag_items = [
        ('MIX', 'Mix Transparency', '', 0),
        ('ADD', 'Add Transparency', '', 2)
    ]
    image: PointerProperty(type=bpy.types.Image)
    max_lod: IntProperty(name="Max LOD", default=1)
    enable_mipmaps: BoolProperty(name="Custom Mip LOD",  default=False)
    enable_highlight: BoolProperty(name="Enable Highlight",  default=False)
    wrap_x: EnumProperty(name="Wrap X", items=wrap_items, default='CLAMP')
    wrap_y: EnumProperty(name="Wrap Y", items=wrap_items, default='CLAMP')
    filter_mode: EnumProperty(name="Filter", items=filter_items, default='LINEAR')
    scale: FloatVectorProperty(name="Scale", min=0, size=3, default=[1, 1, 1])
    translate: FloatVectorProperty(name="Translate",size=3, default=[0, 0, 0])
    rotation: FloatVectorProperty(name="Rotation",size=3, default=[0, 0, 0])
    blend_combiner: EnumProperty(name="Blend Combiner", items=blend_combiner_flag_items, default='ADD')
    blend_alpha: FloatVectorProperty(name="Combiner Blend", size=1, min=0, max=1, default=[1.0])
    enable_alpha: BoolProperty(name="Enable Alpha",  default=False)
    bump_map: FloatProperty(name="Bump Map Intensity", default=0.0, min=0, max=1)
    texture_usage: FloatProperty(name="Texture Usage", default=1.0, min=0, max=1)
    unknown_5: FloatProperty(name="Unknown 5", default=0.0)
    unknown_6: FloatProperty(name="Unknown 6", default=0.0)

    texture_flags: bpy.props.IntProperty(default=0)

    @staticmethod
    def _enum_items(context):
        imgs = bpy.data.images
        items = []
        for i, img in enumerate(sorted(imgs, key=lambda o: o.name)):
            items.append((img.name, img.name, f"Image \"{img.name}\"", "IMAGE", i))
        if not items:
            items.append(("NONE", "None", "No images in the scene", "ERROR", 0))
        return items

    def _set_pointer_from_name(self, context):
        name = self.animated_bitmap_name
        image = bpy.data.images.get(name)

    def set_animated_image(self, img):
        self.animated_bitmap_name = img.name

    animated_bitmap_name: EnumProperty(
        name="Animated Bitmap",
        description="Select an image to key for animating",
        items=lambda self, ctx: HSFTextureMapProperties._enum_items(ctx),
        update=lambda self, ctx: self._set_pointer_from_name(ctx),
    )

class HSFTextureProperties(bpy.types.PropertyGroup):
    image_format: EnumProperty(
        name="Format",
        description="Choose image format",
        items=[
            ('I4', "I4", "", 0),
            ('I8', "I8", "", 1),
            ('IA4', "IA4", "", 2),
            ('IA8', "IA8", "", 3),
            ('RGB565', "RGB565", "", 4),
            ('RGB5A3', "RGB5A3", "", 5),
            ('RGBA32', "RGB5A3", "", 6),
            ('CMPR', "CMPR", "", 7),
            # Palette types
            ('C8_RGB565', "C8_RGB565", "", 9),
            ('C8_RGB5A3', "C8_RGB5A3", "", 10),
            ('C8_IA8', "C8_IA8", "", 11),

            ('C4_RGB565', "C4_RGB565", "", 12),
            ('C4_RGB5A3', "C4_RGB5A3", "", 13),
            ('C4_IA8', "C4_IA8", "", 14),
        ],
        default='CMPR',
    )
    tint_color: FloatVectorProperty(name="Tint Color",  subtype='COLOR', size=3, min=0, max=1, default=[0, 0, 0])
    enable_mipmaps: BoolProperty(name="Enable Mipmaps",  default=False)

    def get_tint_color_u32(self):
        scale = 255.0 / 1.0
        r = int(self.tint_color[0] * scale)
        g = int(self.tint_color[1] * scale)
        b = int(self.tint_color[2] * scale)
        a = 0
        return (a << 24) | (b << 16) | (g << 8) | r

class HSFMaterialProperties(bpy.types.PropertyGroup):
    updated: BoolProperty(default=False)

    vertex_type_items = [
        ('FLAT', 'Flat', '', 0),
        ('SHADING', 'Shading', '', 1),
        ('SPECULAR', 'Specular', '', 2),
        ('SPECULAR2', 'Specular 2', '', 3),
        ('VERTEX_ALPHA', 'Vertex Alpha', '', 4),
        ('VERTEX_COLOR', 'Vertex Color+Alpha', '', 5),
    ]
    blend_type_items = [
        ('SRC_ALPHA_ONE', 'Additive', '', 0),
        ('ZERO_INV_SRC_COLOR', 'Inverse', '', 1),
        ('SRC_ALPHA_INV_SRC_ALPHA', 'Transparent', '', 2),
    ]

    unknown_1: bpy.props.IntProperty(default=0)
    pass_flag: bpy.props.IntProperty(default=0)
    vertex_type: EnumProperty(
        name="Vertex Type", 
        items=vertex_type_items,
        description="Sets the vertex raster type controlling lighting and vertex colors.",
        default='SHADING')

    amb_color: FloatVectorProperty(
        name="Ambient Color",  
        subtype='COLOR', 
        size=4,
        min=0, 
        max=1, 
        description="Sets the ambient color set in the raster channel.",
        default=[0.5, 0.5, 0.5, 1])

    mat_color: FloatVectorProperty(
        name="Material Color",  
        subtype='COLOR', 
        size=4, 
        min=0, 
        max=1, 
        description="Sets the material color set in the raster channel.",
        default=[1, 1, 1, 1])

    shad_color: FloatVectorProperty(
        name="Shadow Color",  
        subtype='COLOR', 
        size=4, 
        min=0,
        max=1, 
        description="Sets the shadow color used when the mesh is a shadow type.",
        default=[0, 0, 0, 1])

    light_map_scale: FloatProperty(
        name="Lightmap Scale", 
        description="Scales the light map.",
        default=50.0,
        min=0)

    unknown_2: FloatProperty(
        name="Unknown 2")

    inverted_transparency: FloatProperty(
        name="Inverted Transparency", 
        description="Controls the transparency amount in the material.",
        default=0.0, 
        min=0, 
        max=1)

    unknown_3: FloatProperty(
        name="Unknown 3")

    unknown_4: FloatProperty(
        name="Unknown 4")

    reflection_intensity: FloatProperty(
        name="Reflection Intensity", 
        description="Blends a reflection texture to the material.",
        default=0.0,
        min=0, 
        max=1)

    unknown_5: FloatProperty(
        name="Unknown 5", default=1.0)

    def reset_flags(self, context):
        if self.flags_reseting or self.flags_changing:
            return

        self.flags_reseting = True
        hsf_flags = hsf_file.HsfMatFlags(self.flags)
        self.set_flags(hsf_flags)
        self.flags_reseting = False

    def set_flags(self, hsf_flags):
        self.flags_changing = True
        self.flags = hsf_flags.flags
        self.enable_lightmap = hsf_flags.has_lightmap
        self.show_both_faces = hsf_flags.show_all_faces
        self.enable_billboard = hsf_flags.has_billboard
        self.has_shadow = hsf_flags.has_shadow
        self.has_shadow_map = hsf_flags.has_shadow_map
        self.enable_depthwrite = hsf_flags.depth_write
        self.is_visible = hsf_flags.is_visible
        self.alpha_test = hsf_flags.alpha_test
        self.mat_hook = hsf_flags.mat_hook
        self.reflect_model = hsf_flags.reflect_model

        set_enum_int(self, "blend_type", hsf_flags.flag_blend_mode)
        self.flags_changing = False

    def update_flags(self, context):
        if self.flags_changing:
            return

        hsf_flags = hsf_file.HsfMatFlags(self.flags)
        hsf_flags.has_lightmap = self.enable_lightmap
        hsf_flags.depth_write = self.enable_depthwrite
        hsf_flags.has_billboard = self.enable_billboard
        hsf_flags.show_all_faces = self.show_both_faces
        hsf_flags.alpha_test = self.alpha_test
        hsf_flags.has_shadow = self.has_shadow
        hsf_flags.has_shadow_map = self.has_shadow_map
        hsf_flags.mat_hook = self.mat_hook
        hsf_flags.reflect_model = self.reflect_model
        hsf_flags.is_visible = self.is_visible
        hsf_flags.flag_blend_mode = get_enum_int(self, "blend_type", self.blend_type)
        hsf_flags.apply_flag_properties()
        # Finally set the raw flag value
        self.flags = hsf_flags.flags
        print(f"update_flags {hsf_flags.flags}")


    flags: IntProperty(
        name="Raw Flags")

    # flag related
    enable_lightmap: bpy.props.BoolProperty(default=False, update=update_flags)
    enable_depthwrite: bpy.props.BoolProperty(default=True, update=update_flags)
    enable_billboard: bpy.props.BoolProperty(default=False, update=update_flags)
    show_both_faces: bpy.props.BoolProperty(default=False, update=update_flags)
    alpha_test: bpy.props.BoolProperty(default=False, update=update_flags)
    has_shadow: bpy.props.BoolProperty(default=False, update=update_flags)
    has_shadow_map: bpy.props.BoolProperty(default=False, update=update_flags)
    transparent_pass: bpy.props.BoolProperty(default=False, update=update_flags)
    is_visible: bpy.props.BoolProperty(default=False, update=update_flags)
    mat_hook: bpy.props.BoolProperty(default=False, update=update_flags)
    reflect_model: bpy.props.BoolProperty(default=False, update=update_flags)

    blend_type: EnumProperty(name="Blend Type", items=blend_type_items, default='SRC_ALPHA_INV_SRC_ALPHA')

    texture_maps: CollectionProperty(name="Texture Maps",type=HSFTextureMapProperties)
    selected_texture_map_index: IntProperty(name="Selected Texture Map Index", default=0)

    flags_changing = False
    flags_reseting = False

    def add_texture_map(self, img):
        tex_map = self.texture_maps.add()
        tex_map.name = img.name
        tex_map.image = img
        return tex_map

    def set_first_texture_map(self, img):
        if len(self.texture_maps) == 0:
            tex_map = self.texture_maps.add()
        else:
            tex_map = self.texture_maps[0]
        tex_map.name = img.name
        tex_map.image = img
        return tex_map

class MATERIAL_UL_texturemap_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        ob = data
        if item and item.image:
            layout.prop(item.image, "name", text="", emboss=False, icon_value=icon)
        else:
            layout.label(text="", translate=False, icon_value=icon)

class HSF_blender_assign_base_color_textures(bpy.types.Operator):
    bl_idname = "hsf.assign_base_color_textures"
    bl_label = "Transfer Eevee Textures "
    bl_description = "Transfers base color textures over to HSF from eevee engine."

    def execute(self, context):
        for mat in bpy.data.materials:
            if not mat.use_nodes:
                continue

            node_tree = mat.node_tree
            img_nodes = [n for n in node_tree.nodes if n.type == 'TEX_IMAGE']
            for img_node in img_nodes:
                for out_socket in img_node.outputs:
                    if not out_socket.is_linked:
                        continue
                    for link in out_socket.links:
                        to_node   = link.to_node
                        to_socket = link.to_socket
                        # Check if the node is connected to a base color node
                        if to_socket.name in {"Base Color", "Color"}:
                            img = img_node.image
                            # Add/assign to the first hsf texture map slot
                            mat.hsf_properties.set_first_texture_map(img)
                            mat.update_tag()

        return {'FINISHED'}

class HSF_blender_import(bpy.types.Operator, ImportHelper):
    bl_idname = "hsf.blender_import"
    bl_label = "Import HSF"
    bl_description = "Import a binary HSF file."

    filename_ext = ".hsf"
    filter_glob: StringProperty(
        default="*.hsf;",
        options={'HIDDEN'},
    )
    def execute(self, context):
        hsffile = hsf_file.HsfFile.load(self.filepath)
        blender_import.import_hsf(hsffile)

        return {'FINISHED'}
            
class HSF_blender_export(bpy.types.Operator, ExportHelper):
    bl_idname = "hsf.blender_export"
    bl_label = "Export HSF"
    bl_description = "Export to binary HSF file."

    filename_ext = ".hsf"
    filter_glob: StringProperty(
        default="*.hsf;",
        options={'HIDDEN'},
    )
    def execute(self, context):
        hsf = blender_export.create_hsf()
        hsf.save(self.filepath)
        return {'FINISHED'}

class MATERIAL_UL_add_texturemap(bpy.types.Operator):
    bl_idname = "hsf.add_texturemap"
    bl_label = "Add Item"
    bl_description = "Add texture map"

    def execute(self, context):
        properties = context.material.hsf_properties
        new = properties.texture_maps.add()
        new.name = f"Texture Map {len(properties.texture_maps)}"
        # make the new item the active one
        properties.selected_texture_map_index = len(properties.texture_maps) - 1
        return {'FINISHED'}

class MATERIAL_UL_remove_texturemap(bpy.types.Operator):
    bl_idname = "hsf.remove_texturemap"
    bl_label = "Remove Item"
    bl_description = "Remove texture map"

    def execute(self, context):
        properties = context.material.hsf_properties
        idx = properties.selected_texture_map_index
        tlist = properties.texture_maps

        if 0 <= idx < len(tlist):
            tlist.remove(idx)
            properties.selected_texture_map_index = min(max(0, idx - 1), len(tlist) - 1)
        return {'FINISHED'}

class HSFMaterialPropertiesPanel(bpy.types.Panel):
    bl_label = "HSF Material"
    bl_idname = "MATERIAL_PT_properties_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material" 

    @classmethod
    def poll(cls, context):
        return context.material is not None and (context.scene.render.engine == 'HSF_RENDER')

    def draw(self, context):
        layout = self.layout

class HSFObjectPropertiesPanel(bpy.types.Panel):
    bl_label = "HSF Object"
    bl_idname = "MATERIAL_PT_object_properties_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object" 

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw(self, context):
        layout = self.layout
        obj = bpy.context.active_object
        properties = obj.hsf_obj_properties
        layout.prop(properties, "obj_type")
        layout.prop(properties, "flags")
        layout.prop(properties, "order")
        layout.prop(properties, "base_morph")
        if properties.obj_type == "REPLICA":
            layout.prop(properties, "replica_obj", text="Replica")
        if properties.obj_type == "LIGHT":
            light_properties = obj.hsf_light_properties
            layout.prop(light_properties, "target")
            layout.prop(light_properties, "color")
            layout.prop(light_properties, "unk2C")
            layout.prop(light_properties, "ref_distance")
            layout.prop(light_properties, "ref_brightness")
            layout.prop(light_properties, "cutoff")
        if properties.obj_type == "CAMERA":
            camera_properties = obj.hsf_camera_properties
            layout.prop(camera_properties, "target")
            layout.prop(camera_properties, "aspect_dupe")
            layout.prop(camera_properties, "fov")
            layout.prop(camera_properties, "near")
            layout.prop(camera_properties, "far")

class HSFMaterialObjectRenderPropertiesPanel(bpy.types.Panel):
    bl_label = "Object Settings"
    bl_idname = "MATERIAL_PT_material_obj_properties_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material" 
    bl_parent_id = HSFMaterialPropertiesPanel.bl_idname

    @classmethod
    def poll(cls, context):
        return context.material is not None and bpy.context.active_object is not None

    def draw(self, context):
        layout = self.layout
        obj = bpy.context.active_object
        properties = obj.hsf_obj_properties
        layout.prop(properties, "flags")

class HSFMaterialRenderPropertiesPanel(bpy.types.Panel):
    bl_label = "Display Settings"
    bl_idname = "MATERIAL_PT_render_properties_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material" 
    bl_parent_id = HSFMaterialPropertiesPanel.bl_idname

    @classmethod
    def poll(cls, context):
        return context.material is not None

    def draw(self, context):
        layout = self.layout
        properties = context.material.hsf_properties
        layout.prop(properties, "vertex_type")
        layout.prop(properties, "blend_type")
        layout.prop(properties, "enable_lightmap")
        layout.prop(properties, "enable_depthwrite")
        layout.prop(properties, "show_both_faces")
        layout.prop(properties, "alpha_test")
        layout.prop(properties, "flags")
        layout.prop(properties, "pass_flag")

class HSFMaterialColorPropertiesPanel(bpy.types.Panel):
    bl_label = "Material Colors"
    bl_idname = "MATERIAL_PT_color_properties_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material" 
    bl_parent_id = HSFMaterialPropertiesPanel.bl_idname

    @classmethod
    def poll(cls, context):
        return context.material is not None

    def draw(self, context):
        layout = self.layout
        properties = context.material.hsf_properties
        layout.prop(properties, "amb_color")
        layout.prop(properties, "mat_color")
        layout.prop(properties, "shad_color")

class HSFMaterialLightingPropertiesPanel(bpy.types.Panel):
    bl_label = "Material Lighting"
    bl_idname = "MATERIAL_PT_lighting_properties_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material" 
    bl_parent_id = HSFMaterialPropertiesPanel.bl_idname

    @classmethod
    def poll(cls, context):
        return context.material is not None

    def draw(self, context):
        layout = self.layout
        properties = context.material.hsf_properties
        layout.prop(properties, "light_map_scale")
        layout.prop(properties, "reflection_intensity", slider=True)
        layout.prop(properties, "inverted_transparency", slider=True)

class HSFMaterialTextureMapPropertiesPanel(bpy.types.Panel):
    bl_label = "Texture Maps"
    bl_idname = "MATERIAL_PT_texture_map_properties_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material" 
    bl_parent_id = HSFMaterialPropertiesPanel.bl_idname

    @classmethod
    def poll(cls, context):
        return context.material is not None

    def draw(self, context):
        layout = self.layout
        properties = context.material.hsf_properties
        row = layout.row()

        layout.operator(HSF_blender_assign_base_color_textures.bl_idname)

        row.template_list("MATERIAL_UL_texturemap_list", "", properties,
            "texture_maps", properties, "selected_texture_map_index", rows=3)

        col = row.column(align=True)
        col.operator(MATERIAL_UL_add_texturemap.bl_idname, icon='ADD', text="")
        col.operator(MATERIAL_UL_remove_texturemap.bl_idname, icon='REMOVE', text="")

        texture_idx = properties.selected_texture_map_index
        texture_list = properties.texture_maps

        if 0 <= texture_idx < len(texture_list):
            texture_map = texture_list[texture_idx]

            if texture_map.image:
                box = layout.box()

                box.template_ID_preview(texture_map, "image", new="image.new", open="image.open")
                box.prop(texture_map.image.hsf_properties, "image_format")
                box.prop(texture_map.image.hsf_properties, "enable_mipmaps")
                box.prop(texture_map.image.hsf_properties, "tint_color")
            else:
                layout.template_ID_preview(texture_map, "image", new="image.new", open="image.open")
            layout.prop(texture_map, "animated_bitmap_name")



class HSFMaterialSamplerPropertiesPanel(bpy.types.Panel):
    bl_label = "Texture Map Info"
    bl_idname = "MATERIAL_PT_sampler_properties_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material" 
    bl_parent_id = HSFMaterialTextureMapPropertiesPanel.bl_idname

    @classmethod
    def poll(cls, context):
        return context.material is not None

    def draw(self, context):
        layout = self.layout
        properties = context.material.hsf_properties

        texture_idx = properties.selected_texture_map_index
        texture_list = properties.texture_maps

        if not (0 <= texture_idx < len(texture_list)):
            return

        texture_map = texture_list[texture_idx]
        layout.prop(texture_map, "blend_combiner")
        layout.prop(texture_map, "blend_alpha", slider=True)

        layout.prop(texture_map, "wrap_x")
        layout.prop(texture_map, "wrap_y")
        layout.prop(texture_map, "filter_mode")
        layout.prop(texture_map, "enable_alpha")
        layout.prop(texture_map, "enable_mipmaps")
        layout.prop(texture_map, "enable_highlight")

        if texture_map.enable_mipmaps:
            layout.prop(texture_map, "max_lod")

        layout.prop(texture_map, "scale")
        layout.prop(texture_map, "translate")

        layout.prop(texture_map, "bump_map", slider=True)
        layout.prop(texture_map, "texture_usage", slider=True)

        layout.prop(texture_map, "texture_flags")
