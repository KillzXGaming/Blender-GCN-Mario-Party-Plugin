import math
import numpy as np
from dataclasses import dataclass, field
from mathutils import Matrix, Vector, Quaternion, Euler
import bpy
from typing import List, Tuple
from bpy_extras import anim_utils
import re
from bpy_extras.io_utils import axis_conversion

from ..hsf import (
    gx_primitive, hsf_file, gx_tex, hsf_creator
)

from .mesh_utils import (
getVertexColors, getTexCoords, getLoopIdcs,
getPositions, getNormals, getTangents, getIndices, 
getLoopFaceIdcs, getFaceMatIdcs, getVertexWeights, groupIndexToName
)

def get_enum_int(obj, prop_name, current_val):
    prop = obj.bl_rna.properties[prop_name]
    if prop.type == 'ENUM':
        integer_id = prop.enum_items[current_val].value
        return integer_id
    return 0

# Same as the hsf creator vertex
@dataclass(eq=True)
class Vertex:
    position: Tuple[float, float, float]
    normal:   Tuple[float, float, float]
    uv:       Tuple[float, float] = (0.0, 0.0)
    color:   Tuple[int, int, int, int] = (255, 255, 255, 255)
    skin:    Tuple[Tuple[int, float], ...] = field(default_factory=tuple)

class ShapeKey:
    def __init__(self):
        self.name = ""
        self.positions = []

class Polygon:
    def __init__(self):
        self.material = ""
        self.indices = []

R_X_MINUS_90 = Matrix((
    (1,  0,  0, 0),
    (0,  0,  1, 0),
    (0, -1,  0, 0),
    (0,  0,  0, 1),
))

def convert_float_byte(byte_value):
    return min(max(int(byte_value * 255), 0), 255)

def get_index_by_name(items, name):
    for i, item in enumerate(items):
        if item.name == name:
            return i
    return -1

def vec_zup_to_yup(v: Vector) -> Vector:
    return (R_X_MINUS_90 @ v.to_4d()).to_3d()

def rot_zup_to_yup_euler_deg(euler_zup: Euler) -> tuple[float]:
    mat_zup = euler_zup.to_matrix()
    mat4_zup = mat_zup.to_4x4()
    mat4_yup = R_X_MINUS_90 @ mat4_zup
    mat_yup = mat4_yup.to_3x3()
    euler_yup = mat_yup.to_euler('XYZ')
    euler_degrees = [math.degrees(a) for a in euler_yup]
    return (euler_degrees[0], euler_degrees[1], euler_degrees[2])

def create_hsf(collection = None):
    if collection:
        blender_objects = collection.objects
    else:
        blender_objects = bpy.context.scene.objects

    blender_materials = get_used_materials(blender_objects)

    hsf = hsf_file.HsfFile()
    create_hsf_materials(hsf, blender_materials)
    create_hsf_objects(hsf, blender_objects)
    create_hsf_matrices(hsf)
    # Note, animation creation should be done last due to index resolving
    create_hsf_animation(hsf, blender_objects, blender_materials)
    fix_dupe_names(hsf)
    hsf.optimize_attributes()
    hsf.optimize_materials()
    return hsf

def export_hsf(filePath):
    hsf = create_hsf()
    hsf.save(filePath)

def fix_dupe_names(hsf):
    for obj in hsf.objects:
        obj.name = re.sub(r'\.\d{1,4}$', '', obj.name)
    for motion in hsf.motions:
        for track in motion.tracks:
            if track.targetString:
                track.targetString = re.sub(r'\.\d{1,4}$', '', track.targetString)

def get_used_materials(blender_objects):
    materials = []
    for obj in blender_objects:
        if obj.type != "MESH" or obj.get("branch_path_draw", False):
            continue

        mesh = obj.data
        for i, mat in enumerate(mesh.materials):
            if mat is None:
                continue
            materials.append(mat)
    return materials

def create_hsf_materials(hsf, blender_materials):

    hsf.materials = []
    for bmat in blender_materials:
        props = bmat.hsf_properties

        mat = hsf_file.HsfMaterial()
        mat.name = bmat.name
        mat.hiliteScale = props.light_map_scale
        mat.materialColorR = convert_float_byte(props.mat_color[0])
        mat.materialColorG = convert_float_byte(props.mat_color[1])
        mat.materialColorB = convert_float_byte(props.mat_color[2])
        mat.ambientColorR = convert_float_byte(props.amb_color[0])
        mat.ambientColorG = convert_float_byte(props.amb_color[1])
        mat.ambientColorB = convert_float_byte(props.amb_color[2])
        mat.shadowColorR = convert_float_byte(props.shad_color[0])
        mat.shadowColorG = convert_float_byte(props.shad_color[1])
        mat.shadowColorB = convert_float_byte(props.shad_color[2])
        mat.unknown1 = props.unknown_1
        mat.unknown2 = props.unknown_2
        mat.unknown3 = props.unknown_3
        mat.unknown4 = props.unknown_4
        mat.unknown5 = props.unknown_5
        mat.invAlpha = max(props.inverted_transparency, 0.0)
        mat.reflectAlpha = props.reflection_intensity
        mat.vtxMode = get_enum_int(props, "vertex_type", props.vertex_type)
        mat.flag_props = hsf_file.HsfMatFlags(props.flags)

        mat.passFlag = props.pass_flag
        # flags
        #mat.flag_blend_mode = get_enum_int(props, "blend_type", props.blend_type)
       # mat.has_lightmap = props.enable_lightmap
        hsf.materials.append(mat)

        # Texture attributes
        mat.attributeIndices = []
        for textureMapProp in props.texture_maps: # HSFTextureMapProperties
            if not textureMapProp.image: # skip if no image is set
                continue

            attr_idx = create_hsf_attribute(hsf, textureMapProp) 
            mat.attributeIndices.append(attr_idx)

    # Add default if no blender materials are present
    if len(hsf.materials) == 0:
        hsf_creator.create_material("shading", hsf,
                    material_color=(255, 255, 255), 
                    ambient_color=(128, 128, 128),
                    shadow_color=(0, 0, 0),
                    transparency=1.0,
                    reflection=0.0,
                    vtx_mode=hsf_file.HSF_VERTEX_MODE.SHADING,
                    use_lightmap=False,
                    blend_mode=hsf_file.HSF_BLEND_MODE.SRCALPHA_INVSRCALPHA)

def create_hsf_attribute(hsf, props):
    # Todo we need to set original attribute index for external animations
    idx = len(hsf.attributes)
    attr = hsf_file.HsfAttribute()
    hsf.attributes.append(attr)

    attr.name = props.image.name
    attr.texAnimOffset = 0 # set at runtime
    attr.blendingFlag = get_enum_int(props, "blend_combiner", props.blend_combiner)
    attr.alphaFlag = int(props.enable_alpha)
    attr.blendTextureAlpha = float(props.blend_alpha[0])
    attr.nbtEnable = props.bump_map
    attr.textureEnable = props.texture_usage
    attr.texAnimStart_Scale = (props.scale[0], props.scale[1])
    attr.texAnimStart_Translate = (props.translate[0], props.translate[1])
    attr.wrapModeX = get_enum_int(props, "wrap_x", props.wrap_x)
    attr.wrapModeY = get_enum_int(props, "wrap_y", props.wrap_y)
    attr.maxLOD = props.max_lod
    attr.textureFlags = props.texture_flags
    attr.unknown5 = 1.0
    attr.unknown6 = props.unknown_6
    attr.use_nearest_filter = props.filter_mode == "NEAREST";
    attr.use_mipmap_lod = props.enable_mipmaps
    attr.use_hilte_reflect = props.enable_highlight

    print(f"texAnimStart_Scale {attr.texAnimStart_Scale}")

    # Add texture if not present already
    textureIdx = get_index_by_name(hsf.textures, props.image.name)
    if textureIdx == -1:
        textureIdx = create_hsf_texture(hsf, props.image)
    attr.textureIndex = int(textureIdx)
    return idx

def create_hsf_texture(hsf, img):
    idx = len(hsf.textures)

    texture = hsf_file.HsfTexture()
    hsf.textures.append(texture)

    texture.name = img.name
    # HSFTextureProperties
    props = img.hsf_properties
    texture.format = get_enum_int(props, "image_format", props.image_format)
    texture.tint_color = props.get_tint_color_u32()

    w = img.size[0] # width
    h = img.size[1] # height
    dims = tuple(img.size)

    pixels = np.array(img.pixels, dtype=np.float32).reshape((h, w, img.channels))
    pixels = np.pad(pixels, ((0, dims[1] == 0), (0, dims[0] == 0), (0, 4 - img.channels)))

    dims2 = np.array(pixels.shape[:2][::-1], dtype=np.integer)

    texture.import_texture(hsf, pixels, w, h)
    return idx

# data path to channel
# property name = (channel count, channel type (first channel))
ATTRIBUTE_CHANNEL_MAPPER = {}
ATTRIBUTE_CHANNEL_MAPPER["scale"] = (3, hsf_file.HSF_TRACK_CHANNEL.ATTR_SCALE_X)
ATTRIBUTE_CHANNEL_MAPPER["rotation"] = (3, hsf_file.HSF_TRACK_CHANNEL.ATTR_ROTATION_X)
ATTRIBUTE_CHANNEL_MAPPER["translate"] = (3, hsf_file.HSF_TRACK_CHANNEL.ATTR_TRANSLATE_X)
ATTRIBUTE_CHANNEL_MAPPER["blend_alpha"] = (1, hsf_file.HSF_TRACK_CHANNEL.ATTR_COMBINER_BLENDING)
ATTRIBUTE_CHANNEL_MAPPER["bump_map"] = (1, hsf_file.HSF_TRACK_CHANNEL.ATTR_BUMP_INTENSITY)
ATTRIBUTE_CHANNEL_MAPPER["texture_usage"] = (1, hsf_file.HSF_TRACK_CHANNEL.ATTR_TEXTURE_INTENSITY)
ATTRIBUTE_CHANNEL_MAPPER["unknown_5"] = (1, hsf_file.HSF_TRACK_CHANNEL.ATTR_UNKNOWN5)
ATTRIBUTE_CHANNEL_MAPPER["unknown_6"] = (1, hsf_file.HSF_TRACK_CHANNEL.ATTR_UNKNOWN6)

OBJ_CHANNEL_MAPPER = {}
OBJ_CHANNEL_MAPPER["location"] = (3, hsf_file.HSF_TRACK_CHANNEL.TRANSLATE_X)
OBJ_CHANNEL_MAPPER["scale"]    = (3, hsf_file.HSF_TRACK_CHANNEL.SCALE_X)
OBJ_CHANNEL_MAPPER["rotation_euler"] = (3, hsf_file.HSF_TRACK_CHANNEL.ROTATION_X)
OBJ_CHANNEL_MAPPER["visible"] = (-1, hsf_file.HSF_TRACK_CHANNEL.VISIBLE)
OBJ_CHANNEL_MAPPER["hsf_obj_properties.base_morph"] = (-1, hsf_file.HSF_TRACK_CHANNEL.BASE_MORPH)

MATERIAL_CHANNEL_MAPPER = {}
MATERIAL_CHANNEL_MAPPER["hsf_properties.amb_color"] = (3, hsf_file.HSF_TRACK_CHANNEL.AMBIENT_COLOR_R)
MATERIAL_CHANNEL_MAPPER["hsf_properties.mat_color"] = (3, hsf_file.HSF_TRACK_CHANNEL.MATERIAL_COLOR_R)
MATERIAL_CHANNEL_MAPPER["hsf_properties.shad_color"] = (3, hsf_file.HSF_TRACK_CHANNEL.SHADOW_COLOR_R)
MATERIAL_CHANNEL_MAPPER["hsf_properties.light_map_scale"] = (1, hsf_file.HSF_TRACK_CHANNEL.HILITE_SCALE)
MATERIAL_CHANNEL_MAPPER["hsf_properties.unknown_2"] = (1, hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_2)
MATERIAL_CHANNEL_MAPPER["hsf_properties.inverted_transparency"] = (1, hsf_file.HSF_TRACK_CHANNEL.TRANSPARENCY)
MATERIAL_CHANNEL_MAPPER["hsf_properties.unknown_3"] = (1, hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_3)
MATERIAL_CHANNEL_MAPPER["hsf_properties.unknown_4"] = (1, hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_4)
MATERIAL_CHANNEL_MAPPER["hsf_properties.reflection_intensity"] = (1, hsf_file.HSF_TRACK_CHANNEL.REFLECTION_INTENSITY)
MATERIAL_CHANNEL_MAPPER["hsf_properties.unknown_5"] = (1, hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_5)

def get_channel_type(fcurve, track_type):
    if track_type == hsf_file.HSF_TRACK_TYPE.TRANSFORM:
        mapper = OBJ_CHANNEL_MAPPER
    elif track_type == hsf_file.HSF_TRACK_TYPE.MATERIAL:
        mapper = MATERIAL_CHANNEL_MAPPER
    elif track_type == hsf_file.HSF_TRACK_TYPE.ATTRIBUTE:
        mapper = ATTRIBUTE_CHANNEL_MAPPER
    else:
        return 0, None

    for key, item in mapper.items():
        if key in fcurve.data_path:
            return item[1]

    return None

def get_texture_animation_ids(channelbag):
    ids = []
    for i, fcurve in enumerate(channelbag.fcurves):
        if "hsf_properties.texture_maps" in fcurve.data_path:
            m = re.search(r'\.texture_maps\[(\d+)\]', fcurve.data_path)
            idx = int(m.group(1)) if m else 0
            ids.append(idx)
    return ids

def convert_z_to_yup(keys: List[hsf_file.HsfKeyFrame]) -> List[hsf_file.HsfKeyFrame]:
    for k in keys:
        k.value      = -k.value
        k.slope_in   = -k.slope_in
        k.slope_out  = -k.slope_out
    return keys

def create_hsf_animation(hsf, blender_objects, blender_materials):
    print(f"create_hsf_animation")

    motion = hsf_file.HsfMotion()

    motion.name = "opt_evalScene" # default hsf anim name
    motion.frame_count = 0

    # Object animations
    for obj in blender_objects:
        if obj.get("branch_path_draw", False):
            continue

        if obj.animation_data and obj.animation_data.action_slot:
            idx = get_index_by_name(hsf.objects, obj.name)
            # Init with default key values of all keyable properties
            hsf_track_values = create_default_obj_tracks(hsf.objects[idx])
            # Setup blender keys and set it in the channel lookup
            anim_data = obj.animation_data
            channelbag = anim_utils.action_get_channelbag_for_slot(anim_data.action, anim_data.action_slot)

            z_y_up_mapper = [0, 2, 1, 3]
            for i, fcurve in enumerate(channelbag.fcurves):
                # Figure out the first channel based on the f curve data path
                channel_type = get_channel_type(fcurve, hsf_file.HSF_TRACK_TYPE.TRANSFORM)
                print(f"{channel_type} {fcurve.data_path}")
                if channel_type == None:
                    continue
                # Set key frames
                keys = get_keys(fcurve)
                # radians to degrees
                if fcurve.data_path == "rotation_euler":
                    for k in keys:
                        k.value = math.degrees(k.value)
                        k.slope_in = math.degrees(k.slope_in)
                        k.slope_out = math.degrees(k.slope_out)

                channel_idx = fcurve.array_index
                if (fcurve.data_path == "location" or fcurve.data_path == "rotation_euler" or fcurve.data_path == "scale"):
                    channel_idx = z_y_up_mapper[fcurve.array_index]
                
                # Z up to Y up
                if channel_idx == 2 and (fcurve.data_path == "location" or fcurve.data_path == "rotation_euler"):
                    keys = convert_z_to_yup(keys)

                hsf_track_values[channel_type + channel_idx] = keys

            # Make hsf tracks
            for channel_type, value in hsf_track_values.items():
                motion.tracks.append(create_hsf_track(
                    obj.name,
                    0, 
                    value,
                    hsf_file.HSF_TRACK_TYPE.TRANSFORM, 
                    channel_type))

    # Material or texture map/attribute animations
    for mat in blender_materials:
        if mat.animation_data and mat.animation_data.action_slot:
            idx = get_index_by_name(hsf.materials, mat.name)
            if idx == -1: # Material not in hsf
                continue

            # Init with default key values
            hsf_mat_tracks = create_default_material_tracks(hsf.materials[idx])
            # Setup blender keys and set it in the channel lookup
            anim_data = mat.animation_data
            channelbag = anim_utils.action_get_channelbag_for_slot(anim_data.action, anim_data.action_slot)

            # Material animation keys
            for i, fcurve in enumerate(channelbag.fcurves):
                if "hsf_properties.texture_maps" in fcurve.data_path:
                    continue
                # Figure out the first channel based on the f curve data path
                channel_type = get_channel_type(fcurve, hsf_file.HSF_TRACK_TYPE.MATERIAL)
                if channel_type == None:
                    print(f"Warning, channel not supported for curve {fcurve.data_path}-{fcurve.array_index}")
                    continue

                # Set key frames
                hsf_mat_tracks[channel_type + fcurve.array_index] = get_keys(fcurve)

            # Texture map default keys
            hsf_attr_tracks = {}
            texture_maps = get_texture_animation_ids(channelbag)
            for map_idx in texture_maps:
                # Key default attribute properties
                name = mat.hsf_properties.texture_maps[map_idx].image.name
                attr_idx = get_index_by_name(hsf.attributes, name)
                hsf_attr_tracks[map_idx] = create_default_attribute_tracks(hsf.attributes[attr_idx])

            # Texture map animation keys
            for i, fcurve in enumerate(channelbag.fcurves):
                if "hsf_properties.texture_maps" in fcurve.data_path:
                    # Figure out the first channel based on the f curve data path
                    channel_type = get_channel_type(fcurve, hsf_file.HSF_TRACK_TYPE.ATTRIBUTE)
                    if channel_type == None:
                        continue
                    m = re.search(r'\.texture_maps\[(\d+)\]', fcurve.data_path)
                    idx = int(m.group(1)) if m else 0
                    # Set key frames
                    hsf_attr_tracks[idx][channel_type + fcurve.array_index] = get_keys(fcurve)

            # Make hsf material tracks
            for channel_type, value in hsf_mat_tracks.items():
                motion.tracks.append(create_hsf_track(
                    None,
                    idx, 
                    value,
                    hsf_file.HSF_TRACK_TYPE.MATERIAL, 
                    channel_type))
            # Make hsf attribute tracks
            for map_idx, track_lookup in hsf_attr_tracks.items():
                for channel_type, value in track_lookup.items():
                    name = mat.hsf_properties.texture_maps[map_idx].image.name
                    attr_idx = get_index_by_name(hsf.attributes, name)

                    motion.tracks.append(create_hsf_track(
                        None,
                        attr_idx, 
                        value,
                        hsf_file.HSF_TRACK_TYPE.ATTRIBUTE, 
                        channel_type))

    # Max frame count of all the tracks, ensure all keys can be loaded since blender frame range is janky
    for track in motion.tracks:
        for key in track.key_frames:
            motion.frame_count = max(key.frame + 1, motion.frame_count)

   # if len(motion.tracks) > 0:
     #   hsf.motions.append(motion)

# Adds default track values
# HSF typically will key all the possbile properties of an obj or material if an animation is used
def create_default_obj_tracks(obj):
    values = {
        hsf_file.HSF_TRACK_CHANNEL.VISIBLE:          1.0,
        hsf_file.HSF_TRACK_CHANNEL.OBJ_FLAG_25:      1.0,
        hsf_file.HSF_TRACK_CHANNEL.OBJ_FLAG_0x2000: 1.0,
        hsf_file.HSF_TRACK_CHANNEL.OBJ_FLAG_27:     1.0,

        hsf_file.HSF_TRACK_CHANNEL.TRANSLATE_X: obj.data.baseTransform.pos[0],
        hsf_file.HSF_TRACK_CHANNEL.TRANSLATE_Y: obj.data.baseTransform.pos[1],
        hsf_file.HSF_TRACK_CHANNEL.TRANSLATE_Z: obj.data.baseTransform.pos[2],

        hsf_file.HSF_TRACK_CHANNEL.ROTATION_X: obj.data.baseTransform.rot[0],
        hsf_file.HSF_TRACK_CHANNEL.ROTATION_Y: obj.data.baseTransform.rot[1],
        hsf_file.HSF_TRACK_CHANNEL.ROTATION_Z: obj.data.baseTransform.rot[2],

        hsf_file.HSF_TRACK_CHANNEL.SCALE_X: obj.data.baseTransform.sca[0],
        hsf_file.HSF_TRACK_CHANNEL.SCALE_Y: obj.data.baseTransform.sca[1],
        hsf_file.HSF_TRACK_CHANNEL.SCALE_Z: obj.data.baseTransform.sca[2],
    }
    return values

def create_default_material_tracks(mat):
    values = {
        hsf_file.HSF_TRACK_CHANNEL.AMBIENT_COLOR_R:       mat.ambientColorR / 255.0,
        hsf_file.HSF_TRACK_CHANNEL.AMBIENT_COLOR_G:       mat.ambientColorG / 255.0,
        hsf_file.HSF_TRACK_CHANNEL.AMBIENT_COLOR_B:       mat.ambientColorB / 255.0,

        hsf_file.HSF_TRACK_CHANNEL.MATERIAL_COLOR_R:     mat.materialColorR / 255.0,
        hsf_file.HSF_TRACK_CHANNEL.MATERIAL_COLOR_G:     mat.materialColorG / 255.0,
        hsf_file.HSF_TRACK_CHANNEL.MATERIAL_COLOR_B:     mat.materialColorB / 255.0,

        hsf_file.HSF_TRACK_CHANNEL.SHADOW_COLOR_R:       mat.shadowColorR / 255.0,
        hsf_file.HSF_TRACK_CHANNEL.SHADOW_COLOR_G:       mat.shadowColorG / 255.0,
        hsf_file.HSF_TRACK_CHANNEL.SHADOW_COLOR_B:       mat.shadowColorB / 255.0,

        hsf_file.HSF_TRACK_CHANNEL.HILITE_SCALE:         mat.hiliteScale,
        hsf_file.HSF_TRACK_CHANNEL.TRANSPARENCY:         mat.invAlpha,

        hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_3:         mat.unknown3,
        hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_4:         mat.unknown4,
        hsf_file.HSF_TRACK_CHANNEL.REFLECTION_INTENSITY:  mat.reflectAlpha,
        hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_5:         mat.unknown5,
    }
    return values

def create_default_attribute_tracks(attr):
    values = {
        hsf_file.HSF_TRACK_CHANNEL.ATTR_COMBINER_BLENDING:  attr.blendTextureAlpha,
        hsf_file.HSF_TRACK_CHANNEL.ATTR_BUMP_INTENSITY:    attr.nbtEnable,
        57: 0.0,
        60: 0.0,
        hsf_file.HSF_TRACK_CHANNEL.ATTR_BUMP_INTENSITY:    attr.nbtEnable,
        hsf_file.HSF_TRACK_CHANNEL.ATTR_UNKNOWN5:          attr.unknown5,
        hsf_file.HSF_TRACK_CHANNEL.ATTR_UNKNOWN6:          attr.unknown6,

        hsf_file.HSF_TRACK_CHANNEL.ATTR_TRANSLATE_X:       attr.texAnimStart_Translate[0],
        hsf_file.HSF_TRACK_CHANNEL.ATTR_TRANSLATE_Y:       attr.texAnimStart_Translate[1],
        hsf_file.HSF_TRACK_CHANNEL.ATTR_TRANSLATE_Z:       0.0,

        hsf_file.HSF_TRACK_CHANNEL.ATTR_ROTATION_X:        0.0,
        hsf_file.HSF_TRACK_CHANNEL.ATTR_ROTATION_Y:        0.0,
        hsf_file.HSF_TRACK_CHANNEL.ATTR_ROTATION_Z:        0.0,

        hsf_file.HSF_TRACK_CHANNEL.ATTR_SCALE_X:           attr.texAnimStart_Scale[0],
        hsf_file.HSF_TRACK_CHANNEL.ATTR_SCALE_Y:           attr.texAnimStart_Scale[1],
        hsf_file.HSF_TRACK_CHANNEL.ATTR_SCALE_Z:           1.0,
    }
    return values

def create_hsf_track(name, index, values, track_type, channel_type):
    track = hsf_file.HsfTrack()
    track.targetString = name
    track.targetIndex = max(index, 0)
    track.channel = channel_type
    track.type = track_type
    if type(values) is not list: # raw single value
        track.constant = float(values)
        track.interpolation = hsf_file.HSF_CURVE_TYPE.CONSTANT
    elif len(values) == 1: # Only one key, all values are the same
        track.constant = float(values[0].value)
        track.interpolation = hsf_file.HSF_CURVE_TYPE.CONSTANT
    else: # key frame list
        track.key_frames = values
        track.interpolation = hsf_file.HSF_CURVE_TYPE.BEZIER
    return track

def get_fcurves(action):
    for fc in action.fcurves:
        print(f"data_path {fc.data_path}")
        if fc.data_path.startswith("hsf_properties."):
            yield fc

def get_keys(fc):
    keys = []
    kps = fc.keyframe_points
    count = len(kps)

    slope_scale = 60.0

    current_val = 0
    for i, kp in enumerate(kps):
        hk = hsf_file.HsfKeyFrame()
        hk.frame = kp.co.x
        hk.value = kp.co.y
        # If the current value is unchanged from the last key, skip adding the key
        if i > 0 and current_val == hk.value:
            continue

        current_val = hk.value
        hk.slope_in = 0.0
        hk.slope_out = 0.0

        # In slope
        if i > 0:
            hl = kp.handle_left
            if hl.x != kp.co.x:
                hk.slope_in = (kp.co.y - hl.y) / (kp.co.x - hl.x) * slope_scale
        elif i == 0:
            hl = kp.handle_left
            if hl.x != kp.co.x:
                hk.slope_in = (kp.co.y - hl.y) / (kp.co.x - hl.x) * slope_scale


        # Out slope
        if i < count - 1:
            hr = kp.handle_right
            if hr.x != kp.co.x:
                hk.slope_out = (hr.y - kp.co.y) / (hr.x - kp.co.x) * slope_scale
        elif i == count - 1:
            hr = kp.handle_right
            if hr.x != kp.co.x:
                hk.slope_out = (hr.y - kp.co.y) / (hr.x - kp.co.x) * slope_scale

        # Interpolation
        if kp.interpolation == 'CONSTANT':
            hk.slope_in = 0.0
            hk.slope_out = 0.0
        elif kp.interpolation == 'LINEAR' and i < count - 1:
            nxt = kps[i + 1]
            slope = (nxt.co.y - kp.co.y) / (nxt.co.x - kp.co.x)
            hk.slope_in = slope
            hk.slope_out = slope

        keys.append(hk)

    return keys

def create_hsf_objects(hsf, blender_objects):
    # Export blender hiearchy tree
    # First make the tree normally
    # Then use the custom properties to maintain original order/indices
    # Finally resolve the parents
    objects = []
    child_to_parent_name = {}
    obj_to_replica_name = {}
    obj_lookup = {}

    # First attempt to add objects by armature
    # For any missing nodes/bones, those will be added later then re sorted via the original index
    obj_armature = None
    for obj in bpy.context.scene.objects:
        if obj.type != 'ARMATURE':
            continue
        obj_armature = obj
        break

    obj_lookup, child_to_parent_name, bone_matrices = create_hsf_objects_by_armature(hsf, obj_armature)
    arm_lookup = {}
    for arm_obj in obj_lookup.values():
        arm_lookup[arm_obj.name] = arm_obj

    # Add by blender objects
    for bobj in blender_objects:
        if bobj.get("branch_path_draw", False):
            continue

        # Skip camera/light types
        if bobj.type in {'CAMERA', 'LIGHT'}:
            continue

        # Only add if not already in from the armature
        if bobj.name not in obj_lookup:
            # Add HSF object
            hsf_obj = hsf_file.HsfObject()
            hsf_obj.data = hsf_file.HsfObjectData()
            hsf_obj.name = bobj.name
            hsf.objects.append(hsf_obj)
            # Add to lookup for setting up obj parameters
            obj_lookup[bobj.name] = hsf_obj
            # Store parent to resolve later as the order will change
            if bobj.parent:
                child_to_parent_name[bobj.name] = bobj.parent.name

    obj_names = []
    for hsf_obj in hsf.objects:
        obj_names.append(hsf_obj.name)

    use_triangle_strips = True
    has_envelopes = True

    # Assign blender obj properties
    for bobj in blender_objects:
        if bobj.name not in obj_lookup:
            continue
        if bobj.get("branch_path_draw", False):
            continue
        # Skip camera/light types
        if bobj.type in {'CAMERA', 'LIGHT'}:
            continue

        hsf_obj = obj_lookup[bobj.name]
        hsf_obj.type = get_enum_int(bobj.hsf_obj_properties, "obj_type", bobj.hsf_obj_properties.obj_type)
        # Create hsf mesh if mesh data is present
        if bobj.type in {'MESH'}:
            # Convert mesh data
            # We need to convert the obj matrix for the armature tree
            src_matrix = bobj.matrix_world
            dst_matrix = bobj.matrix_world
            if bobj.name in bone_matrices:
                dst_matrix = bone_matrices[bobj.name]

            print(f"src {src_matrix} dst {dst_matrix}")

            hsf_mesh = convert_blender_mesh(hsf, bobj, obj_names,
                has_envelopes, use_triangle_strips, src_matrix, dst_matrix)

            hsf_mesh.data.baseTransform = hsf_obj.data.baseTransform
            hsf_obj.data = hsf_mesh.data
            hsf_obj.type = hsf_file.HSF_OBJECT_TYPE.MESH

        hsf_obj.flag_props.flags = bobj.hsf_obj_properties.flags
        hsf_obj.name = bobj.name
        hsf_obj.index = bobj.hsf_obj_properties.order
        hsf_obj.data.baseMorph = bobj.hsf_obj_properties.base_morph

        location = bobj.location
        rot_deg = bobj.rotation_euler
        hsf_obj.data.baseTransform.sca = (1.0, 1.0, 1.0)

        if bobj.name not in arm_lookup:
            hsf_obj.data.baseTransform.rot = (math.degrees(rot_deg[0]), math.degrees(rot_deg[2]), -math.degrees(rot_deg[1])) # euler degrees 
            hsf_obj.data.baseTransform.pos = (location[0], location[2], -location[1])
            hsf_obj.data.baseTransform.sca = (bobj.scale[0], bobj.scale[2], bobj.scale[1])
        else:
            arm_obj = arm_lookup[bobj.name]
            hsf_obj.data.baseTransform = arm_obj.data.baseTransform
            print(f"arm_obj {arm_obj.data.baseTransform.pos}")

        if hsf_obj.type == 1 and bobj.hsf_obj_properties.replica_obj:
            obj_to_replica_name[bobj.name] = bobj.hsf_obj_properties.replica_obj.name
        elif hsf_obj.type == 1:
            print(f"Warning. No replica object set for object {obj.name}")

        if hsf_obj.type == 7:
            hsf_obj.data = hsf_file.HsfCamera()
        if hsf_obj.type == 8:
            light_props = bobj.hsf_light_properties
            hsf_obj.data = hsf_file.HsfLight()
            hsf_obj.data.pos = (location[0], location[2], -location[1])
            hsf_obj.data.target = (light_props.target[0], light_props.target[2], -light_props.target[1])
            hsf_obj.data.type = 2
            hsf_obj.data.r = int(light_props.color[0] * 255)
            hsf_obj.data.b = int(light_props.color[1] * 255)
            hsf_obj.data.g = int(light_props.color[2] * 255)
            hsf_obj.data.unk2C = light_props.unk2C
            hsf_obj.data.ref_distance = light_props.ref_distance
            hsf_obj.data.ref_brightness = light_props.ref_brightness
            hsf_obj.data.cutoff = light_props.cutoff

    # Sort by index
    hsf.objects.sort(key=lambda o: o.index)

    for new_index, obj in enumerate(hsf.objects):
        obj.index = new_index

    # Indices
    name_to_new_index = {obj.name: obj.index for obj in hsf.objects}

    # Map replica indices
    for obj in hsf.objects:
        if obj.type == 1 and obj.name in obj_to_replica_name:
            replica_name = obj_to_replica_name[obj.name]
            obj.data.replicaIndex = name_to_new_index.get(replica_name, -1)
            print(f"{obj.name} -> {replica_name} {obj.data.replicaIndex}")
        elif obj.type == 1:
            print(f"Warning. No replica index set for object {obj.name}")

    # Map parent indices
    for obj in hsf.objects:
        parent_name = child_to_parent_name.get(obj.name)
        if parent_name is not None:
            obj.data.parentIndex = name_to_new_index.get(parent_name, -1)
            if obj.data.parentIndex != -1:
                hsf.objects[obj.data.parentIndex].data.childrenIndices.append(obj.index)
        else:
            obj.data.parentIndex = -1

def getLocalSRT(bone: bpy.types.PoseBone, prevRots):
    rot_y_up = Euler((math.radians(90), 0, 0), 'XYZ')
    rot_y_up_matrix = rot_y_up.to_matrix().to_4x4()
    rot_y_up_matrix_inv = rot_y_up_matrix.inverted().to_4x4()

    if bone.parent:
        parent_world = bone.parent.matrix
        local_mat = parent_world.inverted() @ bone.matrix
    else:
        local_mat = bone.matrix.copy()

   # local_mat = rot_y_up_matrix_inv @ local_mat @ rot_y_up_matrix   # safer roundtrip

    scale = local_mat.to_scale()

    try:
        rot_rad = local_mat.to_euler("XYZ", prevRots[bone])
    except KeyError:
        rot_rad = local_mat.to_euler("XYZ")
    prevRots[bone] = rot_rad
    trans = local_mat.to_translation()

    rot_deg = [math.degrees(a) for a in rot_rad]
    print(f"{bone.name} {rot_deg}")

    return (scale, rot_deg, trans)

def create_hsf_objects_by_armature(hsf, armObj):
    # When rigging is used, we use an armature for a node tree rather than blender objects
    # The user can still include additional blender objects to the tree if present
    # Blender objects will attach back to this armature and merge based on the same naming
    if not armObj:
        return ({}, {}, {})

    obj_lookup = {}
    child_to_parent_name = {}
    bone_infos = []
    prevRots = {}
    bone_matrices = {}

    rot_y_up = Euler((math.radians(90), 0, 0), 'XYZ')
    rot_y_up_matrix = rot_y_up.to_matrix().to_4x4()
    rot_y_up_matrix_inv = rot_y_up_matrix.inverted().to_4x4()

    for poseBone in armObj.pose.bones:
        bone_matrices[poseBone.name] = rot_y_up_matrix_inv @ poseBone.matrix.copy()

        bone = poseBone.bone
        # Skip "skeleton" bone used for Y up rotation
        if poseBone.name == "skeleton":
            continue

        hsf_obj = hsf_file.HsfObject()
        hsf.objects.append(hsf_obj)

        scale, rot, loc = getLocalSRT(poseBone, prevRots)

        hsf_obj.name = poseBone.name
        hsf_obj.data = hsf_file.HsfObjectData()
        hsf_obj.data.baseTransform.pos = (loc.x, loc.y, loc.z)
        hsf_obj.data.baseTransform.rot = (rot[0], rot[1], rot[2])
        hsf_obj.data.baseTransform.sca = (scale.x, scale.y, scale.z)
        obj_lookup[hsf_obj.name] = hsf_obj

        # Matrices for transforming the vertices when a mesh is parenting the bone
        # Assign parenting
        if bone.parent:
            child_to_parent_name[bone.name] = bone.parent.name

    return obj_lookup, child_to_parent_name, bone_matrices

def create_hsf_matrices(hsf):
    if len(hsf.envelopes) == 0:
        return

    matrices = hsf_file.HsfMatrixList()
    hsf.matrices.append(matrices)

    num_meshes = len(hsf.faces)
    num_objs = len(hsf.objects)

    for i in range(num_meshes):
        matrices.meshMatrices.append(hsf_file.HsfMatrix())
    for i in range(num_objs):
        matrices.nodeMatrices.append(hsf_file.HsfMatrix())
    for i in range((num_meshes * num_objs)):
        matrices.allMatrices.append(hsf_file.HsfMatrix())

    for obj in hsf.objects:
        if hasattr(obj.data, "baseTransform"):
            skel = hsf_file.HsfSkeleton()
            skel.name = obj.name
            skel.transform = obj.data.baseTransform
            hsf.skeletons.append(skel)

def convert_blender_mesh(hsf, bobj, obj_names, has_envelopes,
        use_triangle_strips, src_matrix, dst_matrix):
    material_index = 0

    mesh = bobj.to_mesh()
    mesh.calc_loop_triangles()
    # Blender 4.0 removes this as it is no longer needed, keep for 3.0 versions
    if hasattr(mesh, "calc_normals_split"):
        mesh.calc_normals_split()


    idc = getLoopIdcs(mesh)
    positions = getPositions(mesh, idc)
    normals = getNormals(mesh)
    tex_coords = []
    colors = []
    # channel types
    if len(mesh.color_attributes) > 0:
        colors = getVertexColors(mesh, idc,  mesh.color_attributes[0].name)
    if len(mesh.uv_layers) > 0:
        tex_coords = getTexCoords(mesh,  mesh.uv_layers[0].name)
        
    # skinning data
    skin_count, boneWeights, boneIndices = getVertexWeights(mesh, idc)
    boneGroupsToName = groupIndexToName(bobj)

    print(f"{mesh.name} boneIndices {boneIndices.any()}")

    # Make full vertex list
    vertices = []
    for i in range(len(positions)):
        vertex_color = (1.0, 1.0, 1.0, 1.0)
        if len(colors) > 0:
            vertex_color = (min(int(colors[i][0] * 255.0), 255),
                            min(int(colors[i][1] * 255.0), 255),
                            min(int(colors[i][2] * 255.0), 255),
                            min(int(colors[i][3] * 255.0), 255))

        if skin_count: # Ensure world matrix is applied
            pos_local = Vector(positions[i])
            nor_local = Vector(normals[i])

            # To world
            pos_world = src_matrix @ pos_local.to_4d()
            nor_world = src_matrix.to_3x3().inverted().transposed() @ nor_local
            nor_world.normalize()

            # To new local space position
            pos_local = dst_matrix.inverted().to_4x4() @ pos_world.to_4d()
            nor_local = dst_matrix.to_3x3().transposed() @ nor_world
            nor_local.normalize()

            # Z to Y up
            position = Vector((pos_local[0], pos_local[2], -pos_local[1]))
            normal = Vector((nor_local[0], nor_local[2], -nor_local[1]))
        else:
            position = (positions[i][0], positions[i][2], -positions[i][1])
            normal = (normals[i][0], normals[i][2], -normals[i][1])

        vert = Vertex(
            position = position,
            normal =  normal,
            uv = (tex_coords[i][0], tex_coords[i][1]),
            color = vertex_color,
        )

        if skin_count:
            vert_skins = []
            for j in range(skin_count):
                bone_group_idx = boneIndices[i][j]
                bone_weight = boneWeights[i][j]
                bone_name = boneGroupsToName[bone_group_idx]
                bone_idx = obj_names.index(bone_name)
                vert_skins.append((bone_idx, bone_weight))
            vert.skin = tuple(vert_skins)

        vertices.append(vert)

    indices = getIndices(mesh).reshape(-1)
    matLoopIdcs = np.zeros(indices.shape)
    if len(mesh.materials) > 1: # lookup is wasteful if there's only one material
        matLoopIdcs = getFaceMatIdcs(mesh)[getLoopFaceIdcs(mesh)][indices]

    # Material mapping
    material_slots: dict[bpy.types.Material, list[int]] = {}
    for i, mat in enumerate(mesh.materials):
        if mat is None:
            continue

        if mat in material_slots:
            material_slots[mat].append(i)
        else:
            material_slots[mat] = [i]

    # make polygons with indices per material
    polygons: List[Polygon] = []
    if None in material_slots: # No materials
        poly = Polygon()
        poly.indices = indices
        polygons.append(poly)
    elif (len(mesh.materials) == 1): # One material
        poly = Polygon()
        poly.indices = indices
        poly.material = mesh.materials[0].name
        polygons.append(poly)
    else: # Multiple material maps in one mesh, split per polygon object
        for mat, idcs in material_slots.items():
            poly = Polygon()
            poly.indices = indices[np.isin(matLoopIdcs, idcs)]
            poly.material = mat.name
            polygons.append(poly)

    vertex_count = len(positions / 3)
    shape_keys = get_blender_shape_keys(bobj, idc)

    return hsf_creator.create_mesh(bobj.name, hsf,
                vertices=vertices,
                polygons=polygons,
                shape_keys=shape_keys,
                use_triangle_strips=use_triangle_strips,
                has_envelopes=has_envelopes)

def get_blender_shape_keys(obj, idc):
    shapes = []

    if obj.type != 'MESH' or not obj.data.shape_keys:
        return shapes

    # Make a shape for every shape key
    basis_block = obj.data.shape_keys.key_blocks.get("Basis") or obj.data.shape_keys.key_blocks[0]

    n_verts = len(basis_block.data)
    basis_coords = np.empty((n_verts, 3), dtype=np.float32)
    basis_block.data.foreach_get('co', basis_coords.ravel())

    for key in obj.data.shape_keys.key_blocks:
        if key.name == basis_block.name:
            continue

        shape_key = ShapeKey()
        shapes.append(shape_key)

        shape_key.name = key.name
        # Get vertices relative to the key basis
        delta_coords = np.empty_like(basis_coords)
        key.data.foreach_get('co', delta_coords.ravel())
        absolute_coords = basis_coords + delta_coords

        # Y up
        absolute_coords = absolute_coords[:, (0, 2, 1)]
        absolute_coords[:, 2] *= -1.0 

        shape_key.positions = absolute_coords[idc].astype(np.float32, copy=False)

    return shapes
