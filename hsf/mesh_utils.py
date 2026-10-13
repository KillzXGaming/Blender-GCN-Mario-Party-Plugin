import bpy, gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector, Euler
import math

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