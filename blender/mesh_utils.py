import bpy, gpu
import array
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector, Euler
import math
import ctypes
import numpy as np

def groupIndexToName(obj: bpy.types.Object) -> dict[int, str]:
    return {g.index: g.name for g in obj.vertex_groups}

def getVertexWeights(mesh, idc):
    n_verts = len(mesh.vertices)
    max_influences = 4
    weights   = np.zeros((n_verts, max_influences), dtype=np.float32)
    bone_ids  = np.zeros((n_verts, max_influences), dtype=np.int32)
    max_skin_count = 0

    for vi, v in enumerate(mesh.vertices):
        groups = [(g.group, g.weight) for g in v.groups]
        if not groups: # no rigging
            continue  

        # Sort by weight by largest to smallest
        groups.sort(key=lambda x: x[1], reverse=True)
        # Clamp to max
        top = groups[:max_influences]
        for slot, (grp_idx, w) in enumerate(top):
            bone_ids[vi, slot] = int(grp_idx)
            weights[vi, slot] = w

        max_skin_count = max(max_skin_count, len(top))
        # normalize
        total = weights[vi].sum()
        if total > 0.0:
            weights[vi] /= total

    return max_skin_count, weights[idc], bone_ids[idc]

def getVertexColors(mesh, idc, vertex_color_layer_name):
    if vertex_color_layer_name not in mesh.color_attributes:
        return None

    layer = mesh.color_attributes[vertex_color_layer_name]
    colors = np.empty(len(layer.data) * 4, dtype=np.float32)
    layer.data.foreach_get("color", colors)
    colors = colors.reshape((-1, 4))

    c = colors[idc]

    return c

def getTexCoords(mesh, uv_layer_name):
    if uv_layer_name not in mesh.uv_layers:
        return None

    # Get the uv layer
    layer = mesh.uv_layers[uv_layer_name]
    uvs = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", uvs)
    return uvs.reshape((-1, 2))

def getLoopIdcs(mesh):
    indices = np.empty(len(mesh.loops), 'i')
    mesh.loops.foreach_get("vertex_index", np.reshape(indices, len(mesh.loops)))
    return indices

def getPositions(mesh, idc):
    positions = np.empty((len(mesh.vertices), 3), 'f')
    mesh.vertices.foreach_get("co", np.reshape(positions, len(mesh.vertices) * 3))
    return positions[idc]

def getNormals(mesh):
    normals = np.empty((len(mesh.loops), 3), 'f')
    mesh.loops.foreach_get("normal", np.reshape(normals, len(mesh.loops) * 3))
    return normals

def getTangents(mesh):
    mesh.calc_tangents()

    tangents = np.empty(len(mesh.loops) * 3, dtype=np.float32)
    mesh.loops.foreach_get("tangent", tangents)
    tangents = tangents.reshape((-1, 3))

    bitangent_signs = np.empty(len(mesh.loops), dtype=np.float32)
    mesh.loops.foreach_get("bitangent_sign", bitangent_signs)

    print(str(np.column_stack((tangents, bitangent_signs))))

    return np.column_stack((tangents, bitangent_signs))

def getIndices(mesh):
    indices = np.empty((len(mesh.loop_triangles), 3), 'i')
    mesh.loop_triangles.foreach_get("loops", np.reshape(indices, len(mesh.loop_triangles) * 3))
    return indices

def getLoopFaceIdcs(mesh: bpy.types.Mesh):
    loop_face_counts  = np.empty(len(mesh.polygons), 'i')
    mesh.polygons.foreach_get("loop_total", loop_face_counts)
    return np.arange(len(mesh.polygons)).repeat(loop_face_counts )

def getFaceMatIdcs(mesh: bpy.types.Mesh):
    mat_indices = np.empty(len(mesh.polygons), 'i')
    mesh.polygons.foreach_get("material_index", mat_indices)
    return mat_indices

def rotation_matrix_deg(euler_deg, order='XYZ'):
    rad = [math.radians(a) for a in euler_deg]
    eul = Euler(rad, order)
    return eul.to_matrix().to_4x4()

def scale_matrix(scale_vec):
    sx, sy, sz = scale_vec
    return Matrix.Diagonal((sx, sy, sz, 1.0))


def get_or_create_attributes_float_vector(mesh, bm, attr_name):
    if not attr_name in mesh.attributes:
        attr = mesh.attributes.new(name=attr_name, type='FLOAT_VECTOR', domain='POINT')

    return bm.verts.layers.float_vector.get(attr_name)

def get_or_create_attributes_float(mesh, bm, attr_name):
    if not attr_name in mesh.attributes:
        attr = mesh.attributes.new(name=attr_name, type='FLOAT', domain='POINT')

    return bm.verts.layers.float.get(attr_name)

def get_or_create_attributes_int(mesh, bm, attr_name):
    if not attr_name in mesh.attributes:
        attr = mesh.attributes.new(name=attr_name, type='INT', domain='POINT')

    return bm.verts.layers.int.get(attr_name)

def make_custom_cube_batch(width: float = 4.0,
                           height: float = 4.0,
                           depth: float = 4.0):
    hx = width  * 0.5
    hy = height * 0.5
    hz = depth  * 0.5
    verts = [
        (-hx, -hy, -hz),
        ( hx, -hy, -hz),
        ( hx,  hy, -hz),
        (-hx,  hy, -hz),
        (-hx, -hy,  hz),
        ( hx, -hy,  hz),
        ( hx,  hy,  hz),
        (-hx,  hy,  hz),
    ]

    faces = [
        (0, 1, 2), (0, 2, 3),   # -Z
        (4, 6, 5), (4, 7, 6),   # +Z
        (0, 4, 5), (0, 5, 1),   # -Y
        (1, 5, 6), (1, 6, 2),   # +X
        (2, 6, 7), (2, 7, 3),   # +Y
        (3, 7, 4), (3, 4, 0),   # -X
    ]

    tri_verts = [verts[i] for tri in faces for i in tri]

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES', {"pos": tri_verts})
    return shader, batch

def make_cube_batch(size=4.0):
    verts = [
       (-size, -size, -size),
        (size, -size, -size),
        (size, size, -size),
        (-size, size, -size),
        (-size, -size, size),
        (size, -size, size),
        (size, size, size),
        (-size, size, size),
    ]

    faces = [
        (0, 1, 2), (0, 2, 3),   # -Z
        (4, 6, 5), (4, 7, 6),   # +Z
        (0, 4, 5), (0, 5, 1),   # -Y
        (1, 5, 6), (1, 6, 2),   # +X
        (2, 6, 7), (2, 7, 3),   # +Y
        (3, 7, 4), (3, 4, 0),   # -X
    ]

    tri_verts = [verts[i] for tri in faces for i in tri]

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": tri_verts})
    return shader, batch

def make_plane_batch(size: float = 4.0):
    verts = [
        (-size, -size, 0.0),
        ( size, -size, 0.0),
        ( size,  size, 0.0),
        (-size,  size, 0.0),
    ]

    uvs = [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0), 
        (0.0, 1.0),
    ]

    faces = [
        (0, 1, 2), 
        (0, 2, 3),
    ]
    tri_verts = [verts[i] for f in faces for i in f]
    uvs_verts = [uvs[i] for f in faces for i in f]

    shader = gpu.shader.from_builtin('IMAGE_COLOR')
    batch  = batch_for_shader(shader, 'TRIS', {"pos": tri_verts, "texCoord": uvs_verts})
    return shader, batch

def make_cone_batch(height=1.0, radius=0.2, segments=16):
    verts = [(0, 0, height)] # tip

    for i in range(segments):
        angle = 2 * 3.14159265359 * i / segments
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        verts.append((x, y, 0.0))

    faces = []
    tip_index = 0
    for i in range(1, segments):
        faces.append((tip_index, i, i + 1))
    faces.append((tip_index, segments, 1)) 

    tris = [verts[i] for f in faces for i in f]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = batch_for_shader(shader, 'TRIS', {"pos": tris})
    return shader, batch