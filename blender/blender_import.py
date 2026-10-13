import bpy
from collections import defaultdict
import mathutils
from mathutils import Matrix, Vector, Quaternion, Euler
from typing import List, Tuple
import math
from bpy_extras import anim_utils
from bpy_extras.io_utils import axis_conversion

from ..hsf import (
    gx_primitive, hsf_file
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

def flat_to_triangles(flat: List[int]) -> List[Tuple[int, int, int]]:
    return [(flat[i], flat[i + 1], flat[i + 2])
            for i in range(0, len(flat), 3)]

def _vertex_normals_to_loop_normals(mesh, vnormals):
    vnorm = [n.normalized() for n in vnormals]
    return [vnorm[loop.vertex_index] for loop in mesh.loops]

def get_local_hsf_matrix(obj):
    if hasattr(obj.data, "baseTransform"):
        sca = obj.data.baseTransform.sca
        pos = obj.data.baseTransform.pos
        rot = obj.data.baseTransform.rot # euler degrees

        bone_translation = Vector((pos[0], -pos[2], pos[1]))
        bone_scale = Vector((sca[0], sca[2], sca[1]))
        bone_rotation = Euler((math.radians(rot[0]), math.radians(-rot[2]), math.radians(rot[1])), 'XYZ').to_quaternion()

        return matrix_trs(bone_translation,bone_rotation,(1,1,1))
    else:
       return Matrix((
		(1.0, 0.0, 0.0, 0.0),
		(0.0, 0.0, -1.0, 0.0),
		(0.0, 1.0, 0.0, 0.0),
		(0.0, 0.0, 0.0, 1.0)))

def import_hsf(hsfFile:hsf_file.HsfFile ):
    # Cleanup past imports
    for material in bpy.data.materials:
        if not material.users:
            bpy.data.materials.remove(material)

    blender_tex_attributes = {} # dict of attr index with an array of HSFTextureMap properties
    blender_objects_name_lookup = {}

    bmats = []
    for i, mat in enumerate(hsfFile.materials):
        bmat = create_blender_material(mat, i, hsfFile, blender_tex_attributes)
        bmats.append(bmat)

    print(f"slot_to_blender_index {len(bmats)}")

    hasJoints = False
    for obj in hsfFile.objects: # List[HSFObject]
        if obj.type == 4: # HSF_OBJECT_TYPE.JOINT
            hasJoints = True

    blender_objects = {}
    for obj in hsfFile.objects: # List[HSFObject]
        local_matrix = get_local_hsf_matrix(obj)
        if obj.type == 2:
            gx_meshes = gx_primitive.convert_gx_meshes(hsfFile, obj)
            blender_mesh, vertex_groups_list = import_blender_mesh(gx_meshes, bmats, obj, hsfFile)
            blender_obj = bpy.data.objects.new(blender_mesh.name, blender_mesh)
            bpy.context.collection.objects.link(blender_obj)
            blender_objects[obj.index] = blender_obj

            # Assign vertex groups
            for mesh_groups in vertex_groups_list:
                for bone_name, weight_list in mesh_groups.items():
                    # Make or get vertex group for adding weight data
                    if bone_name not in blender_obj.vertex_groups:
                        vg = blender_obj.vertex_groups.new(name=bone_name)
                    else:
                        vg = blender_obj.vertex_groups[bone_name]

                    for vert_idx, weight in weight_list:
                        vg.add([vert_idx], weight, 'REPLACE')

           # blender_obj.matrix_local = local_matrix
        else:
            blender_obj = bpy.data.objects.new(obj.name, None)
            bpy.context.collection.objects.link(blender_obj)
            blender_objects[obj.index] = blender_obj

         #   blender_obj.matrix_local = local_matrix

        if hasattr(obj.data, "baseTransform"):
            sca = obj.data.baseTransform.sca
            pos = obj.data.baseTransform.pos
            rot = obj.data.baseTransform.rot # euler degrees
            blender_obj.scale = (sca[0], sca[2], sca[1])
            blender_obj.location = (pos[0], -pos[2], pos[1])
            blender_obj.rotation_euler = (math.radians(rot[0]), math.radians(-rot[2]), math.radians(rot[1]))

        if obj.type == 8: # light
            light_props = blender_obj.hsf_light_properties
            light = obj.data # HsfLight
            blender_obj.location = (light.pos[0], -light.pos[2], light.pos[1])
            light_props.target = (light.target[0], -light.target[2], light.target[1])
            light_props.color = (light.r / 255.0, light.g / 255.0, light.b / 255.0)
            light_props.unk2C = light.unk2C
            light_props.ref_distance = light.ref_distance
            light_props.ref_brightness = light.ref_brightness
            light_props.cutoff = light.cutoff
        if obj.type == 7: # camera
            cam_props = blender_obj.hsf_camera_properties
            cam = obj.data # HsfCamera
            cam_props.target = (cam.target[0], -cam.target[2], cam.target[1])
            cam_props.far = cam.far
            cam_props.near = cam.near
            cam_props.aspect_dupe = cam.aspect_dupe
            cam_props.fov = cam.fov

        blender_obj.hsf_obj_properties.order = obj.index
        blender_obj.hsf_obj_properties.flags = obj.flag_props.flags
        set_enum_int(blender_obj.hsf_obj_properties, "obj_type", obj.type)

        # For animations
        blender_objects_name_lookup[obj.name] = blender_obj

    if hasJoints:
        armature_obj, matrices = create_blender_armature("Model", hsfFile.objects)
        # Assign armature to each mesh with vertex groups
        for bobj in blender_objects.values():
            if bobj.type == "MESH" and bobj.vertex_groups:
                mod = bobj.modifiers.new(name="Armature", type='ARMATURE')
                mod.object = armature_obj
                mod.use_vertex_groups = True

    # Set replicate obj properties
    for i, obj in enumerate(hsfFile.objects):
        if obj.type == 1 and len(blender_objects) > obj.data.replicaIndex and obj.data.replicaIndex != -1:
            replica_obj = blender_objects[obj.data.replicaIndex]
            blender_objects[i].hsf_obj_properties.set_replica_obj(replica_obj)
    
    # resolve parents
    for obj in hsfFile.objects:
	    if hasattr(obj.data, "parentIndex") and obj.data.parentIndex != -1 and obj.data.parentIndex < len(hsfFile.objects):
		    if obj.index != obj.data.parentIndex:
			    print(f"parentIndex {obj.data.parentIndex}")
			    blender_objects[obj.index].parent = blender_objects[obj.data.parentIndex]

    for motion in hsfFile.motions:
        import_animation(motion, bmats, blender_objects_name_lookup, blender_tex_attributes)

def create_blender_material(material, index, hsfFile, blender_tex_attributes):
    mat_name = f"mat{index}_{material.name}"
    bmat = bpy.data.materials.new(name=mat_name)

    props = bmat.hsf_properties
    props.unknown_1 = material.unknown1
    props.pass_flag = material.passFlag
    set_enum_int(props, "vertex_type", material.vtxMode)
    props.amb_color[0] = material.ambientColorR / 255.0
    props.amb_color[1] = material.ambientColorG / 255.0
    props.amb_color[2] = material.ambientColorB / 255.0
    props.mat_color[0] = material.materialColorR / 255.0
    props.mat_color[1] = material.materialColorG / 255.0
    props.mat_color[2] = material.materialColorB / 255.0
    props.shad_color[0] = material.shadowColorR / 255.0
    props.shad_color[1] = material.shadowColorG / 255.0
    props.shad_color[2] = material.shadowColorB / 255.0
    props.light_map_scale = material.hiliteScale
    props.unknown_2 = material.unknown2
    props.inverted_transparency = material.invAlpha
    props.unknown_3 = material.unknown3
    props.unknown_4 = material.unknown4
    props.reflection_intensity = material.reflectAlpha
    props.unknown_5 = material.unknown5
    props.flags = material.flag_props.flags
    props.set_flags(material.flag_props)

    for i, idx in enumerate(material.attributeIndices):
        attr = hsfFile.attributes[idx]

        tex = hsfFile.textures[attr.textureIndex]
        img = create_blender_texture(tex, attr.textureIndex, hsfFile)

        texMap = props.add_texture_map(img)
        texMap.max_lod = attr.maxLOD
        set_enum_int(texMap, "wrap_x", attr.wrapModeX)
        set_enum_int(texMap, "wrap_y", attr.wrapModeY)
        set_enum_int(texMap, "blend_combiner", attr.blendingFlag)
        texMap.blend_alpha[0] = attr.blendTextureAlpha
        texMap.bump_map = attr.nbtEnable
        texMap.enable_alpha = attr.alphaFlag != 0
        texMap.texture_map = attr.textureEnable
        texMap.scale[0] = attr.texAnimStart_Scale[0]
        texMap.scale[1] = attr.texAnimStart_Scale[1]
        texMap.translate[0] = attr.texAnimStart_Translate[0]
        texMap.translate[1] = attr.texAnimStart_Translate[1]

        if idx not in blender_tex_attributes:
            blender_tex_attributes[idx] = []
        # The material for animating later, and the slot index
        blender_tex_attributes[idx].append((bmat, i))

    return bmat

def create_blender_texture(tex, textureIndex, hsfFile):
    name = f"tex{textureIndex}_{tex.name}"
    rgba = tex.get_rgba(hsfFile)
    w = tex.width
    h = tex.height

    if name in bpy.data.images:
        return bpy.data.images[name]

    img = bpy.data.images.new(name=name, width=w, height=h, alpha=True, float_buffer=False)
    pixels = [0.0] * (w * h * 4)
    row_stride = w * 4
    for row in range(h):
        src_row = h - 1 - row
        src_start = src_row * row_stride
        dst_start = row * row_stride
        for i in range(row_stride):
            pixels[dst_start + i] = rgba[src_start + i]

    img.pixels = pixels
    img.pack()

    set_enum_int(img.hsf_properties, "image_format", tex.format)

    print(f"texture.format {img.hsf_properties.image_format} og {tex.format}")

    return img

mat_channel_to_blender_data_path = {
    hsf_file.HSF_TRACK_CHANNEL.AMBIENT_COLOR_R:       ("hsf_properties.amb_color", 0),
    hsf_file.HSF_TRACK_CHANNEL.AMBIENT_COLOR_G:       ("hsf_properties.amb_color", 1),
    hsf_file.HSF_TRACK_CHANNEL.AMBIENT_COLOR_B:       ("hsf_properties.amb_color", 2),

    hsf_file.HSF_TRACK_CHANNEL.MATERIAL_COLOR_R:     ("hsf_properties.mat_color", 0),
    hsf_file.HSF_TRACK_CHANNEL.MATERIAL_COLOR_G:     ("hsf_properties.mat_color", 1),
    hsf_file.HSF_TRACK_CHANNEL.MATERIAL_COLOR_B:     ("hsf_properties.mat_color", 2),

    hsf_file.HSF_TRACK_CHANNEL.SHADOW_COLOR_R:       ("hsf_properties.shad_color", 0),
    hsf_file.HSF_TRACK_CHANNEL.SHADOW_COLOR_G:       ("hsf_properties.shad_color", 1),
    hsf_file.HSF_TRACK_CHANNEL.SHADOW_COLOR_B:       ("hsf_properties.shad_color", 2),

    hsf_file.HSF_TRACK_CHANNEL.HILITE_SCALE:         ("hsf_properties.light_map_scale", -1),
    hsf_file.HSF_TRACK_CHANNEL.TRANSPARENCY:         ("hsf_properties.inverted_transparency", -1),

    hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_3:         ("hsf_properties.unknown_3", -1),
    hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_4:         ("hsf_properties.unknown_4", -1),
    hsf_file.HSF_TRACK_CHANNEL.REFLECTION_INTENSITY:  ("hsf_properties.reflection_intensity", -1),
    hsf_file.HSF_TRACK_CHANNEL.MAT_UNKNOWN_5:         ("hsf_properties.unknown_5", -1),
}

attr_channel_to_blender_data_path = {
    hsf_file.HSF_TRACK_CHANNEL.ATTR_SCALE_X:         ("scale", 0),
    hsf_file.HSF_TRACK_CHANNEL.ATTR_SCALE_Y:         ("scale", 1),
    hsf_file.HSF_TRACK_CHANNEL.ATTR_SCALE_Z:         ("scale", 2),

    hsf_file.HSF_TRACK_CHANNEL.ATTR_ROTATION_X:         ("rotation", 0),
    hsf_file.HSF_TRACK_CHANNEL.ATTR_ROTATION_Y:         ("rotation", 1),
    hsf_file.HSF_TRACK_CHANNEL.ATTR_ROTATION_Z:         ("rotation", 2),

    hsf_file.HSF_TRACK_CHANNEL.ATTR_TRANSLATE_X:     ("translate", 0),
    hsf_file.HSF_TRACK_CHANNEL.ATTR_TRANSLATE_Y:     ("translate", 1),
    hsf_file.HSF_TRACK_CHANNEL.ATTR_TRANSLATE_Z:     ("translate", 2),

    hsf_file.HSF_TRACK_CHANNEL.ATTR_COMBINER_BLENDING: ("blend_alpha", -1),

    hsf_file.HSF_TRACK_CHANNEL.ATTR_BUMP_INTENSITY:    ("bump_map", -1),
    hsf_file.HSF_TRACK_CHANNEL.ATTR_TEXTURE_INTENSITY: ("texture_usage", -1),
    hsf_file.HSF_TRACK_CHANNEL.ATTR_UNKNOWN5:          ("unknown_5", -1),
    hsf_file.HSF_TRACK_CHANNEL.ATTR_UNKNOWN6:          ("unknown_6", -1),
}

obj_channel_to_blender_data_path = {
    hsf_file.HSF_TRACK_CHANNEL.TRANSLATE_X:         ("location", 0),
    hsf_file.HSF_TRACK_CHANNEL.TRANSLATE_Y:         ("location", 2), # Y to Z up
    hsf_file.HSF_TRACK_CHANNEL.TRANSLATE_Z:         ("location", 1),
    hsf_file.HSF_TRACK_CHANNEL.ROTATION_X:          ("rotation_euler", 0),
    hsf_file.HSF_TRACK_CHANNEL.ROTATION_Y:          ("rotation_euler", 2), # Y to Z up
    hsf_file.HSF_TRACK_CHANNEL.ROTATION_Z:          ("rotation_euler", 1),
    hsf_file.HSF_TRACK_CHANNEL.SCALE_X:             ("scale", 0),
    hsf_file.HSF_TRACK_CHANNEL.SCALE_Y:             ("scale", 2), # Y to Z up
    hsf_file.HSF_TRACK_CHANNEL.SCALE_Z:             ("scale", 1),
    hsf_file.HSF_TRACK_CHANNEL.VISIBLE:             ("hsf_obj_properties.visible", -1),
}

camera_channel_to_blender_data_path = {
    hsf_file.HSF_TRACK_CHANNEL.CAMERA_POS_X:         ("location", 0), # Y to Z up
    hsf_file.HSF_TRACK_CHANNEL.CAMERA_POS_Y:         ("location", 2),
    hsf_file.HSF_TRACK_CHANNEL.CAMERA_POS_Z:         ("location", 1),
    hsf_file.HSF_TRACK_CHANNEL.CAMERA_TARGET_X:      ("hsf_camera_properties.target", 0),
    hsf_file.HSF_TRACK_CHANNEL.CAMERA_TARGET_Y:      ("hsf_camera_properties.target", 1),
    hsf_file.HSF_TRACK_CHANNEL.CAMERA_TARGET_Z:      ("hsf_camera_properties.target", 2),
    hsf_file.HSF_TRACK_CHANNEL.CAMERA_ASPECT:        ("hsf_camera_properties.aspect", -1),
    hsf_file.HSF_TRACK_CHANNEL.CAMERA_FOV:           ("hsf_camera_properties.fov", -1),
}

light_channel_to_blender_data_path = {
    hsf_file.HSF_TRACK_CHANNEL.LIGHT_POS_X:         ("location", 0), # Y to Z up
    hsf_file.HSF_TRACK_CHANNEL.LIGHT_POS_Y:         ("location", 2),
    hsf_file.HSF_TRACK_CHANNEL.LIGHT_POS_Z:         ("location", 1),
    hsf_file.HSF_TRACK_CHANNEL.LIGHT_AIM_X:         ("hsf_light_properties.target", 0),
    hsf_file.HSF_TRACK_CHANNEL.LIGHT_AIM_Y:         ("hsf_light_properties.target", 1),
    hsf_file.HSF_TRACK_CHANNEL.LIGHT_AIM_Z:         ("hsf_light_properties.target", 2),
}

def import_animation(motion, blender_materials, blender_objects, blender_tex_attributes):
    for track in motion.tracks:
        if track.type == hsf_file.HSF_TRACK_TYPE.TRANSFORM:
            if track.targetString in blender_objects:
                blender_obj = blender_objects[track.targetString]
                import_blender_object_animation(track, blender_obj)

        elif track.type == hsf_file.HSF_TRACK_TYPE.MATERIAL:
            # Materials set by index. The list should match the hsf material list
            if len(blender_materials) > track.targetIndex and track.targetIndex != -1:
                blender_mat = blender_materials[track.targetIndex]
                import_blender_material_animation(track, blender_mat)
            pass
        elif track.type == hsf_file.HSF_TRACK_TYPE.ATTRIBUTE:
            if track.targetIndex in blender_tex_attributes:
                for blender_mat, idx in blender_tex_attributes[track.targetIndex]:
                    import_blender_texture_animation(track, blender_mat, idx)
        elif track.type == hsf_file.HSF_TRACK_TYPE.MORPH: # TODO
            pass
        elif track.type == hsf_file.HSF_TRACK_TYPE.CLUSTER: # TODO
            pass
        elif track.type == hsf_file.HSF_TRACK_TYPE.CLUSTER_WEIGHT: # TODO
            pass

def convert_y_to_zup(keys: List[hsf_file.HsfKeyFrame]) -> List[hsf_file.HsfKeyFrame]:
    for k in keys:
        k.value      = -k.value
        k.slope_in   = -k.slope_in
        k.slope_out  = -k.slope_out
    return keys

def convert_deg_to_radians(keys: List[hsf_file.HsfKeyFrame]) -> List[hsf_file.HsfKeyFrame]:
    for k in keys:
        k.value      = math.radians(k.value)
        k.slope_in   = math.radians(k.slope_in)
        k.slope_out  = math.radians(k.slope_out)
    return keys

def import_blender_object_animation(track, blender_obj):
    channel_to_data_path = obj_channel_to_blender_data_path
    obj_type = blender_obj.hsf_obj_properties.obj_type
    if obj_type == 7: # camera
        channel_to_data_path = camera_channel_to_blender_data_path
    elif obj_type == 8: # light
        channel_to_data_path = light_channel_to_blender_data_path

    if track.channel not in channel_to_data_path:
        print(f"Warning object type {obj_type} channel {track.channel} not supported!")
        return

    if blender_obj.animation_data is None:
        blender_obj.animation_data_create()

    # Negate Z axis (which is used as Y) (Y to Z up conversion)
    keys = track.key_frames
    constant_value = track.constant
    if track.channel in (10, 13, 30):
        keys = convert_y_to_zup(track.key_frames)
        constant_value = -constant_value

    # Rotation degrees to radians
    if track.channel in (28, 29, 30):
        keys = convert_deg_to_radians(keys)
        constant_value = math.radians(constant_value)

    data_path, data_index = obj_channel_to_blender_data_path[track.channel]
    anim_data = blender_obj.animation_data
    fcurve = create_fcurve(anim_data, blender_obj.name, data_path, data_index, "OBJECT")
    load_blender_curve(fcurve, track.interpolation, constant_value, keys)

def import_blender_material_animation(track, blender_mat):
    if track.channel not in mat_channel_to_blender_data_path:
        print(f"Warning material channel {track.channel} not supported!")
        return

    if blender_mat.animation_data is None:
        blender_mat.animation_data_create()

    data_path, data_index = mat_channel_to_blender_data_path[track.channel]

    anim_data = blender_mat.animation_data
    fcurve = create_fcurve(anim_data, blender_mat.name, data_path, data_index, "MATERIAL")

    load_blender_curve(fcurve, track.interpolation, track.constant, track.key_frames)

def import_blender_texture_animation(track, blender_mat, index):
    if track.channel not in attr_channel_to_blender_data_path:
        print(f"Warning attribute channel {track.channel} not supported!")
        return

    if blender_mat.animation_data is None:
        blender_mat.animation_data_create()

    data_path_end, data_index = attr_channel_to_blender_data_path[track.channel]

    # The data path is structured like
    # hsf_properties.texture_maps[0].scale[0]
    data_path = f"hsf_properties.texture_maps[{index}].{data_path_end}"
    anim_data = blender_mat.animation_data
    fcurve = create_fcurve(anim_data, blender_mat.name, data_path, data_index, "MATERIAL")

    print(f"data_path {data_path}")

    load_blender_curve(fcurve, track.interpolation, track.constant, track.key_frames)

def create_fcurve(anim_data, action_name, data_path, data_index, slot_type="MATERIAL"):
    if bpy.app.version < (5, 0, 0): # blender 5.0 changed fcurves, older versions use action.fcurves
        if not anim_data.action:
            anim_data.action = bpy.data.actions.new(name=f"{action_name}_Action")
        for fcurve in anim_data.action.fcurves:
            if fcurve.data_path == data_path and fcurve.array_index == data_index:
                return fcurve

        return anim_data.action.fcurves.new(data_path=data_path, index=data_index)

    if not anim_data.action:
        # Make new action and slot
        action = bpy.data.actions.new(name=f"{action_name}_Action")
        action_slot = action.slots.new(slot_type, "Slot")
        # Assign to anim
        anim_data.action = action
        anim_data.action_slot = action_slot
        channelbag = anim_utils.action_ensure_channelbag_for_slot(action, action_slot)
    else:
        channelbag = anim_utils.action_get_channelbag_for_slot(anim_data.action, anim_data.action.slots[0])

    print(f"data_path test {data_path} {data_index}")

    for fc in channelbag.fcurves:
        if fc.data_path == data_path and fc.array_index == data_index:
            return fc

    # Make the curve
    return channelbag.fcurves.new(data_path=data_path, index=data_index)

def load_blender_curve(fcurve, interpolation, constant:float, keys: List[hsf_file.HsfKeyFrame]):
    keys = sorted(keys, key=lambda k: k.frame)

    fcurve.keyframe_points.clear()
    fcurve.keyframe_points.add(count=len(keys))

    if interpolation == 4: # Constant
        fcurve.keyframe_points.clear()
        fcurve.keyframe_points.add(count=1)

        kp = fcurve.keyframe_points[0]
        kp.co = (0.0, constant)
    if interpolation in (0, 3): # Step or bitmap
        for i, hsf in enumerate(keys):
            kp = fcurve.keyframe_points[i]
            kp.co = (hsf.frame, hsf.value)
    elif interpolation == 1: # Linear
        for i, hsf in enumerate(keys):
            kp = fcurve.keyframe_points[i]
            kp.co = (hsf.frame, hsf.value)
            kp.interpolation = 'LINEAR' 
    elif interpolation == 2: # Bezier
        # hsf has the frame scale baked into slopes, so apply a scale to get the right slope handles
        slope_scale = 1.0 / 60.0
        for i, k in enumerate(keys):
            kp = fcurve.keyframe_points[i]
            kp.co = (k.frame, k.value)

            def _handle_offset(dx, slope):
                return (dx / 3.0, (slope * slope_scale * dx) / 3.0)

            if i == 0:
                dx = 1.0
                ox, oy = _handle_offset(dx, k.slope_in)
                kp.handle_left = (k.frame - ox, k.value - oy)
            else:
                prev = keys[i - 1]
                dx = k.frame - prev.frame
                ox, oy = _handle_offset(dx, k.slope_in)
                kp.handle_left = (k.frame - ox, k.value - oy)


            if i == len(keys) - 1:
                dx = 1.0
                ox, oy = _handle_offset(dx, k.slope_out)
                kp.handle_right = (k.frame + ox, k.value + oy)
            else:
                nxt = keys[i + 1]
                dx = nxt.frame - k.frame
                ox, oy = _handle_offset(dx, k.slope_out)
                kp.handle_right = (k.frame + ox, k.value + oy)

            kp.handle_left_type  = kp.handle_right_type = 'FREE'
            kp.interpolation = 'BEZIER' 

    fcurve.update()

def import_blender_mesh(meshes, bmats, hsf_obj, hsfFile):
    vertex_start = 0
    positions = []
    normals = []
    boneIndices = []
    boneWeights = []
    color_layers = []
    indices = []
    loop_uvs = []
    colors_list = []
    poly_mat_ids= []

    vertex_groups_list = []
    blender_material_slots = []
    for mat_idx, mesh in meshes.items():
        slot_idx = len(blender_material_slots)

        blender_material = bmats[mat_idx]
        blender_material_slots.append(blender_material)

        uv_set = []
        mesh_vertex_groups = {} # bone_name -> list of (vert_idx, weight)
        for vert_idx, vertex in enumerate(mesh.vertices):
            positions.append(vertex.position)
            normals.append(vertex.normal)
            uv_set.append(vertex.tex_coord)
            color_layers.append(vertex.color)

            if hasattr(vertex, 'weights') and vertex.weights:
                for bone_idx, weight in vertex.weights:
                    if weight <= 0.0:
                        continue
                    bone_name = hsfFile.objects[bone_idx].name
                    if bone_name not in mesh_vertex_groups:
                        mesh_vertex_groups[bone_name] = []
                    mesh_vertex_groups[bone_name].append((vertex_start + vert_idx, weight))
        # UVs
        for i in mesh.indices:
            loop_uvs.append(uv_set[i])
        # Faces (triangles)
        for i in range(len(mesh.indices)):
            indices.append(mesh.indices[i] + vertex_start)

        n_triangles = len(mesh.indices) // 3
        poly_mat_ids += [slot_idx] * n_triangles
        vertex_start += len(mesh.vertices)

        vertex_groups_list.append(mesh_vertex_groups)

    blender_mesh = create_blender_mesh(
        name=hsf_obj.name,
        # Z up conversion
        positions=[(v[0], -v[2], v[1]) for v in positions],
        normals=[(v[0], -v[2], v[1]) for v in normals],
        indices=indices,
        loop_uvs=loop_uvs,
        color_layers=color_layers,
        poly_mat_ids=poly_mat_ids,
        blender_material_slots=blender_material_slots,
    )

    return blender_mesh, vertex_groups_list

def create_blender_mesh(name, positions, indices, normals=None,
  loop_uvs=None, color_layers=None, poly_mat_ids =None, blender_material_slots=None):
    mesh = bpy.data.meshes.new(name)

    mesh.from_pydata(
        positions,
        [],
        [indices[i:i+3] for i in range(0, len(indices), 3)]
    )
    mesh.update(calc_edges=True)
    for bmat in blender_material_slots:
        mesh.materials.append(bmat)

    if normals:
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
        if hasattr(mesh, "use_auto_smooth"):
            mesh.use_auto_smooth = True

        #Normalize just incase
        normalized_normals = [mathutils.Vector(n).normalized() for n in normals]

        loop_normals = _vertex_normals_to_loop_normals(mesh, normalized_normals)
        mesh.normals_split_custom_set(loop_normals)

        mesh.normals_split_custom_set_from_vertices(normalized_normals)

    if loop_uvs:
        uv_layer = mesh.uv_layers.new(name=f"UVMap_0")
        for loop, uv in zip(mesh.loops, loop_uvs):
            uv_layer.data[loop.index].uv = uv

    if color_layers:
        color_attr = mesh.color_attributes.new(
            name=f"Color_0",
            type='FLOAT_COLOR',
            domain='POINT'
        )
        # Set per-vertex colors
        for i in range(len(color_layers)):
            color_attr.data[i].color = color_layers[i]

    if poly_mat_ids:
        for i, poly in enumerate(mesh.polygons):
            poly.material_index = poly_mat_ids[i]
    return mesh


def create_blender_armature(model_name, bones, is_quat = False, tail_length=0.5):
    # Create armature object
    arm_data = bpy.data.armatures.new(name=f"{model_name}_Armature")
    arm_obj = bpy.data.objects.new(f"{model_name}_Armature", arm_data)
    arm_obj.show_in_front = True

    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')
    edit_bones = arm_data.edit_bones

    # Set matrices
    bone_map = {}
    local_matrices = {}

    rot_y_up = Euler((math.radians(90), 0, 0), 'XYZ')

    root_bone = edit_bones.new("skeleton")
    root_bone.head = (0, 0, 0)
    root_bone.tail = (0, tail_length, 0)
    root_bone.matrix = rot_y_up.to_matrix().to_4x4()

    # Create bones
    for obj in bones:
        eb = edit_bones.new(obj.name)
        bone_map[obj.index] = eb

    # Set parents
    for obj in bones:
        if hasattr(obj.data, "parentIndex") and obj.data.parentIndex != -1:
            print(f"parentIndex {obj.data.parentIndex}")
            parent_eb = bone_map.get(obj.data.parentIndex)
            if parent_eb:
                bone_map[obj.index].parent = parent_eb
            else:
                bone_map[obj.index].parent = root_bone
        else:
            bone_map[obj.index].parent = root_bone

    # Create local matrices
    for obj in bones:
        eb = bone_map[obj.index]
        
        if hasattr(obj.data, "baseTransform"):
            pos = obj.data.baseTransform.pos
            rot = obj.data.baseTransform.rot  # euler degrees
             # ignore scale for now, blender doesn't handle scale well
            # sca = obj.data.baseTransform.sca

            loc = Vector((pos[0], pos[1], pos[2]))
            rot_eul = Euler((math.radians(rot[0]), math.radians(rot[1]), math.radians(rot[2])), 'XYZ')
            scl = Vector((1.0, 1.0, 1.0))

            local_mat = Matrix.LocRotScale(loc, rot_eul, scl)
            local_matrices[obj.name] = local_mat
        else:
            local_matrices[obj.name] = Matrix.Identity(4)

    for obj in bones:
        eb = bone_map[obj.index]
        eb.matrix = root_bone.matrix @ get_world_matrix(obj, bones, local_matrices)

        if eb.length < 0.001:
            eb.length = tail_length

    bpy.ops.object.mode_set(mode='OBJECT')

    return arm_obj, local_matrices

def get_world_matrix(obj, bones, local_matrices):
	matrix = local_matrices[obj.name]
	if hasattr(obj.data, "parentIndex"):
	    if obj.data.parentIndex != -1:
		    return get_world_matrix(bones[obj.data.parentIndex], bones, local_matrices) @ matrix
	return matrix

def matrix_trs(translation,quaternion,scale):
   return Matrix.Translation(translation) @ quaternion.to_matrix().to_4x4() @ Matrix.Scale(scale[0],4,(1,0,0)) @ Matrix.Scale(scale[1],4,(0,1,0)) @ Matrix.Scale(scale[2],4,(0,0,1))

def calculate_armature_matrices(local_matrices,parent_bone):
   #Editbone.matrix is in armature editmode space
   #In order of parent to children, calculate the armature matrices 
   for child in parent_bone.children:
       child.matrix = parent_bone.matrix @ local_matrices[child.name]

   for child in parent_bone.children:
       calculate_armature_matrices(local_matrices,child) 