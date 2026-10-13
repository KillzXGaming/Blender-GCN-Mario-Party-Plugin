import bpy, gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector, Euler
import math
import os
import bmesh

from . mesh_utils import make_plane_batch, make_cone_batch, make_custom_cube_batch, rotation_matrix_deg, scale_matrix
from . path_object import PartyPathPointProps

def init_shader():
    """
    Creates and returns the shader used to display board spaces.
    """
    vert_out = gpu.types.GPUStageInterfaceInfo("my_interface")
    vert_out.smooth('VEC2', "uvInterp")
    shader_info = gpu.types.GPUShaderCreateInfo()
    shader_info.push_constant('MAT4', "ModelViewProjectionMatrix")
    shader_info.push_constant('VEC4', "color")
    shader_info.push_constant('INT', "selected")
    shader_info.push_constant('INT', "spriteIndex")
    shader_info.push_constant('INT', "editMode")

    shader_info.sampler(0, 'FLOAT_2D', "image")
    shader_info.vertex_in(0, 'VEC2', "pos")
    shader_info.vertex_in(1, 'VEC2', "texCoord")
    shader_info.vertex_out(vert_out)
    shader_info.fragment_out(0, 'VEC4', "FragColor")

    shader_info.vertex_source(
        "void main()"
        "{"
        "  uvInterp = texCoord;"
        "  gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);"
        "}"
    )

    shader_info.fragment_source(
        "const float SPRITES_PER_COL = 8.0;"
        "const float SPRITES_PER_ROW = 6.0;"

        "const float SPRITE_TEXEL_W = 1.0 / SPRITES_PER_COL;"
        "const float SPRITE_TEXEL_H = 1.0 / SPRITES_PER_ROW;"

        "vec2 CalcScaleBias(in vec2 uv, in vec4 sb) {"
        "   vec2 uvFlipped = vec2(uv.x, 1.0 - uv.y);"
        "   return uvFlipped.xy * vec2(sb.x, -sb.y) + vec2(sb.z, 1.0 - sb.w);"
        "}"

        "vec2 GetTileUVs()"
        "{"
        "   int col = spriteIndex % 8;"
        "   int row  = spriteIndex / 8;"
        "   vec2 tileOffset = vec2(col, row) * vec2(SPRITE_TEXEL_W, SPRITE_TEXEL_H);"
        "   return CalcScaleBias(uvInterp, vec4(SPRITE_TEXEL_W, SPRITE_TEXEL_H, tileOffset.x, tileOffset.y));"
        "}"

        "void main()"
        "{"
        "  FragColor = texture(image, GetTileUVs()) * color;"
        "  if (selected == 1)"
        "      FragColor.rgb += vec3(0.2);"
        "  if (editMode == 1)"
        "      FragColor.rgb *= vec3(1.1);"
        "}"
    )
    shader = gpu.shader.create_from_info(shader_info)
    return shader

# we only need to make these once

CUBE_SHADER, CUBE_BATCH = make_custom_cube_batch(600, 600, 50)
HOST_PLATFORM_SHADER, HOST_PLATFORM_BATCH = make_custom_cube_batch(300, 300, 50)

PLANE_SHADER, PLANE_BATCH = make_plane_batch()
CONE_SHADER, CONE_BATCH = make_cone_batch(height=0.4, radius=0.2, segments=16)
SPACE_SHADER = init_shader()

LINE_SHADER = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
LINE_BATCH  = None

SPACE_SHEET = None

def get_texture():
    global SPACE_SHEET
    if SPACE_SHEET is None:
        addOnPath = os.path.dirname(__file__)
        img = bpy.data.images.load(str(os.path.join(addOnPath, "PartySheet.png")), check_existing=True)
        SPACE_SHEET = gpu.texture.from_image(img)
    return SPACE_SHEET

def draw_shop_mp4(mvp):
    col = (1.0, 1.0, 1.0, 1.0)

    CUBE_SHADER.bind()
    CUBE_SHADER.uniform_float("color", col)
    CUBE_SHADER.uniform_float("ModelViewProjectionMatrix", mvp)
    CUBE_BATCH.draw(CUBE_SHADER)

def draw_host_platform_mp4(mvp):
    col = (1.0, 1.0, 1.0, 1.0)

    HOST_PLATFORM_SHADER.bind()
    HOST_PLATFORM_SHADER.uniform_float("color", col)
    HOST_PLATFORM_SHADER.uniform_float("ModelViewProjectionMatrix", mvp)
    HOST_PLATFORM_BATCH.draw(HOST_PLATFORM_SHADER)

def draw_path():
    """Draws a set of path points and arrows along party path objects."""
    region = bpy.context.region_data
    if not region:
        return

    texture_sheet = get_texture()

    for obj in bpy.context.visible_objects:
        if obj.type != 'MESH' or not obj.get("branch_path_draw", False):
            continue

        mesh = obj.data
        forward_attr = mesh.attributes.get("Direction")
        type_attr = mesh.attributes.get("Type")
        scale_attr = mesh.attributes.get("Scale")
        rotate_attr = mesh.attributes.get("Rotate")
        flags_attr = mesh.attributes.get("Flags")

        if not forward_attr or not type_attr:
            continue

        # get vertices and edge info
        if obj.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(mesh)
            verts = bm.verts
            edges = bm.edges
            use_bmesh = True
            layer_direction = bm.edges.layers.bool.get("Direction")
            layer_space_type = bm.verts.layers.int.get("Type")
            layer_scale = bm.verts.layers.float_vector.get("Scale")
            layer_rotate = bm.verts.layers.float_vector.get("Rotate")
            layer_flags = bm.verts.layers.int.get("Flags")

            edge_direction = lambda e: bool(e[layer_direction]) 
            get_space_type = lambda e: int(e[layer_space_type]) 
            get_flags = lambda e: int(e[layer_flags]) 

            get_scale = lambda e: list(e[layer_scale]) 
            get_rotate = lambda e: list(e[layer_rotate]) 
        else:
            verts = mesh.vertices
            edges = mesh.edges
            edge_direction = lambda e: forward_attr.data[e.index].value
            get_space_type = lambda e: type_attr.data[e.index].value
            get_flags = lambda e: flags_attr.data[e.index].value

            get_scale = lambda e: scale_attr.data[e.index].vector
            get_rotate = lambda e: rotate_attr.data[e.index].vector
            use_bmesh = False

        if not verts or len(verts) == 0:
            continue

        line_verts_world = []
        line_selected_verts_world = []

        for edge in edges:
            if use_bmesh:
                idx0 = edge.verts[0].index
                idx1 = edge.verts[1].index
            else:
                idx0 = edge.vertices[0]
                idx1 = edge.vertices[1]

            p0_local = verts[idx0].co if use_bmesh else mesh.vertices[idx0].co
            p1_local = verts[idx1].co if use_bmesh else mesh.vertices[idx1].co

            backward = edge_direction(edge)
            # Swap if backward
            if backward:
                p0_local, p1_local = p1_local, p0_local

            p0 = obj.matrix_world @ p0_local
            p1 = obj.matrix_world @ p1_local

            if obj.mode == 'EDIT' and edge.select:
                line_selected_verts_world.append(p0)
                line_selected_verts_world.append(p1)
            else:
                line_verts_world.append(p0)
                line_verts_world.append(p1)

        def get_flags_by_index(v_idx):
            if use_bmesh:
                return get_flags(verts[v_idx])
            else:
                return get_flags(mesh.vertices[v_idx])

        gpu.state.depth_test_set('NONE') 

        global LINE_BATCH
        if line_verts_world:
            LINE_BATCH = batch_for_shader(
                LINE_SHADER,
                'LINES',
                {"pos": line_verts_world},
            )

            LINE_SHADER.bind()
            LINE_SHADER.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
            if obj.mode == 'EDIT':
                LINE_SHADER.uniform_float("color", (0.0, 0.7, 1.0, 1.0))
                LINE_SHADER.uniform_float("lineWidth", 2.7)
            elif obj.select_get():
                LINE_SHADER.uniform_float("color", (1.0, 1.0, 0.0, 1.0))
                LINE_SHADER.uniform_float("lineWidth", 2.2)
            else:
                LINE_SHADER.uniform_float("color", (0.0, 0.7, 1.0, 1.0))
                LINE_SHADER.uniform_float("lineWidth", 2.5)
            LINE_BATCH.draw(LINE_SHADER)

        if line_selected_verts_world:
            LINE_BATCH = batch_for_shader(
                LINE_SHADER,
                'LINES',
                {"pos": line_selected_verts_world},
            )

            LINE_SHADER.bind()
            LINE_SHADER.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
            LINE_SHADER.uniform_float("color", (1.0, 1.0, 0.0, 1.0))
            LINE_SHADER.uniform_float("lineWidth", 2.5)
            LINE_BATCH.draw(LINE_SHADER)

        # Draw direction arrow along directed edges
        arrow_h = 150.5

        for edge in edges:
            # draw from point to child
            if use_bmesh:
                idx0 = edge.verts[0].index
                idx1 = edge.verts[1].index
            else:
                idx0 = edge.vertices[0]
                idx1 = edge.vertices[1]

            p0_local = verts[idx0].co if use_bmesh else mesh.vertices[idx0].co
            p1_local = verts[idx1].co if use_bmesh else mesh.vertices[idx1].co

            backward = edge_direction(edge)
            # Swap if backward
            if backward:
                p0_local, p1_local = p1_local, p0_local

            p0 = obj.matrix_world @ p0_local
            p1 = obj.matrix_world @ p1_local

            line_verts_world.append(p0)
            line_verts_world.append(p1)

            line_dir = p1 - p0
            line_len = line_dir.length
            if line_len == 0.0:
                continue

            mid = (p0 + p1) * 0.5

            col = (1.0, 0.0, 0.0, 1.0)

            quat = line_dir.to_track_quat('Z', 'Y')
            rot_mat = quat.to_matrix().to_4x4()

            scale_mat = Matrix.Scale(arrow_h, 4)
            model = Matrix.Translation(mid) @ rot_mat @ scale_mat
            mvp = region.perspective_matrix @ model

            CONE_SHADER.bind()
            CONE_SHADER.uniform_float("color", col)
            CONE_SHADER.uniform_float("ModelViewProjectionMatrix", mvp)
            CONE_BATCH.draw(CONE_SHADER)

        gpu.state.depth_mask_set(True)  
        gpu.state.blend_set('ALPHA')

        global_scale = 17.0
        for i, vert in enumerate(verts):
            local_pos = vert.co
            world_pos = obj.matrix_world @ local_pos

            selected = 1 if use_bmesh and vert.select else 0
            edit_mode = 1 if obj.mode == 'EDIT' else 0
            flags = get_flags(vert)

            offset = Vector((0.0, 0.0, 0.055))
            col = (1.0, 1.0, 1.0, 1.0)
            space_type = get_space_type(vert)
            sprite_index = mesh.party_properties.get_sprite_index(space_type, flags)

            # space scale
            scale = get_scale(vert)
            # space rotation in euler degrees
            rotate = get_rotate(vert)

            rot_mat = rotation_matrix_deg(rotate)
            scale_mat = scale_matrix((scale[0] * global_scale, scale[1] * global_scale, scale[2] * global_scale))

            model = obj.matrix_world @ Matrix.Translation(local_pos + offset) @ rot_mat @ scale_mat
            mvp = region.perspective_matrix @ model

            SPACE_SHADER.bind()
            SPACE_SHADER.uniform_sampler("image", texture_sheet)
            SPACE_SHADER.uniform_float("color", col)
            SPACE_SHADER.uniform_int("selected", selected)
            SPACE_SHADER.uniform_int("spriteIndex", sprite_index)
            SPACE_SHADER.uniform_int("editMode", edit_mode)
            SPACE_SHADER.uniform_float("ModelViewProjectionMatrix", mvp)
            PLANE_BATCH.draw(SPACE_SHADER)

        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('LESS_EQUAL') 
        gpu.state.depth_mask_set(True)  

        for edge in edges:
            if use_bmesh:
                idx0 = edge.verts[0].index
                idx1 = edge.verts[1].index
            else:
                idx0 = edge.vertices[0]
                idx1 = edge.vertices[1]

            vert1 = verts[idx0]
            vert2 = verts[idx1]

            backward = edge_direction(edge)
            # Swap if backward
            if backward:
                vert1, vert2 = vert2, vert1

            space_type = get_space_type(vert1)

            # Special case, is the space possibly a shop, boo, or lottery model
            flags = get_flags(vert1)
            if flags == 33554432:
                # Draw at the next vertex spot
                scale_mat_inv = scale_matrix(obj.scale).inverted()

                shop_co_local = vert2.co
                shop_co_world = obj.matrix_world @ Matrix.Translation(shop_co_local) @ scale_mat_inv

                mvp = region.perspective_matrix @ shop_co_world
                draw_shop_mp4(mvp)

            # Draw star host platform
            next_flags = get_flags(vert2)
            if next_flags == 67108864 and space_type == 8:
                scale_mat_inv = scale_matrix(obj.scale).inverted()
                co_local = vert2.co

                co_world = obj.matrix_world @ Matrix.Translation(co_local) @ scale_mat_inv
                draw_host_platform_mp4(region.perspective_matrix @ co_world)