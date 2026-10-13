from . gx_primitive import calc_tristrip
from . hsf_file import *
from dataclasses import dataclass, field
import numpy as np
from collections import defaultdict
from typing import List, Tuple

def get_index_by_name(items, name):
    for i, item in enumerate(items):
        if item.name == name:
            return i
    return -1

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

def _to_tuple(arr, *, dtype=float):
    if arr is None:
        return ()
    return tuple(dtype(v) for v in arr)

def get_vertex_key(vert: Vertex):
    return (
        _to_tuple(vert.position, dtype=float),
        _to_tuple(vert.normal,   dtype=float),
        _to_tuple(vert.uv,       dtype=float),
        _to_tuple(vert.color,    dtype=float),
        _to_tuple(vert.skin,     dtype=int),
    )

def create_material(name, hsf,
    material_color:tuple=(255, 255, 255), 
    ambient_color:tuple=(128, 128, 128),
    shadow_color:tuple=(0, 0, 0),
    transparency=1.0,
    reflection=0.0,
    vtx_mode=0,
    blend_mode=0,
    use_billboard=False,
    use_lightmap=False
):
    mat = HsfMaterial()
    mat.name = name
    mat.hiliteScale = 50.0
    mat.materialColorR = material_color[0]
    mat.materialColorG = material_color[1]
    mat.materialColorB = material_color[2]
    mat.ambientColorR = ambient_color[0]
    mat.ambientColorG = ambient_color[1]
    mat.ambientColorB = ambient_color[2]
    mat.shadowColorR = shadow_color[0]
    mat.shadowColorG = shadow_color[1]
    mat.shadowColorB = shadow_color[2]
    mat.invAlpha = max(1.0 - transparency, 0.0)
    mat.reflectAlpha = reflection
    mat.passFlag = 0
    mat.flags = 0
    mat.flag_blend_mode = blend_mode
    mat.vtxMode = vtx_mode
    mat.has_lightmap = use_lightmap
    hsf.materials.append(mat)

def get_material_index(hsf, mat):
    return get_index_by_name(hsf.materials, mat)

def already_in(position, container):
    return any(np.array_equal(position, p) for p in container)

def create_mesh(name, hsf:HsfFile, vertices:List[Vertex],
        polygons:List[Polygon], shape_keys:List[ShapeKey] = [],
        use_triangle_strips=True,
        has_envelopes=False):

    has_attributes = False
    force_vertex_colors = False
    for poly in polygons:
        mat_idx = get_material_index(hsf, poly.material)
        if hsf.materials[mat_idx].vtxMode in (4, 5):
            force_vertex_colors = True
        if len(hsf.materials[mat_idx].attributeIndices) > 0:
            has_attributes = True

    # Create buffers that store all unique positions, normals, uvs, colors
    positions_buf = HsfBuffer()
    normals_buf   = HsfBuffer()
    uvs_buf       = HsfBuffer()
    colors_buf    = HsfBuffer()

    morph_buffer: list[HsfBuffer] = []
    for i in range(len(shape_keys)):
        morph_buffer.append(HsfBuffer())

    position_to_idx = {}
    normal_to_idx   = {}
    uv_to_idx       = {}
    color_to_idx    = {}

    pos_skin_map: dict[int, Tuple[int, float], ...] = {}
    unique_vertex_map: dict[tuple, tuple[int, int, int]] = {}

    vertex_group_dict: dict[int, tuple[int, int, int]] = {}

    # make face data
    face = HsfFace()
    face.name = name
    hsf.faces.append(face)

    has_vertex_colors = force_vertex_colors
    # Check for vertex colors that are not white
    for vert in vertices:
        if vert.color != (255, 255, 255, 255):
            has_vertex_colors = True

    hasSkinning = False
    for i, vert in enumerate(vertices):
        if len(vert.skin) > 0:
            hasSkinning = True
            break


    for i, vert in enumerate(vertices):
        if hasSkinning or len(shape_keys) > 0:
            pos_idx = len(positions_buf.values)
            positions_buf.values.append(vert.position)

            nor_idx = len(normals_buf.values)
            normals_buf.values.append(vert.normal)

            if len(vert.skin) > 0:
                pos_skin_map[pos_idx] = vert.skin
        else:
            pos_idx = position_to_idx.get(vert.position)
            if pos_idx is None:
                pos_idx = len(positions_buf.values)
                position_to_idx[vert.position] = pos_idx
                positions_buf.values.append(vert.position)

            nor_idx = len(normals_buf.values)
            normals_buf.values.append(vert.normal)

        uv_idx = uv_to_idx.get(vert.uv)
        if uv_idx is None:
            uv_idx = len(uvs_buf.values)
            uv_to_idx[vert.uv] = uv_idx
            uvs_buf.values.append(vert.uv)

        if has_vertex_colors:
            col_idx = color_to_idx.get(vert.color)
            if col_idx is None:
                col_idx = len(colors_buf.values)
                color_to_idx[vert.color] = col_idx
                colors_buf.values.append((
                    vert.color[0] / 255.0,
                    vert.color[1] / 255.0,
                    vert.color[2] / 255.0,
                    vert.color[3] / 255.0))
        else:
            col_idx = -1

        vertex_group_dict[i] = (pos_idx, nor_idx, uv_idx, col_idx)

        # Add morph position buffers
        for b, shape in enumerate(shape_keys):
             morph_buffer[b].values.append(shape.positions[i])

    # make triangle primitives
    for poly in polygons:
        triangles = []
        for tri_i in range(len(poly.indices) // 3):
            tri = HsfFacePrimitive()
            tri.type = HSF_PRIMITIVE_TYPE.TRIANGLE
            triangles.append(tri)

            for v_of_tri in range(3):
                idx   = poly.indices[tri_i * 3 + v_of_tri]
                pos_idx, nor_idx, uv_idx, col_idx = vertex_group_dict[idx]

                vg = HsfVertexGroup()
                vg.positionIndex = pos_idx
                vg.normalIndex   = nor_idx
                vg.texCoordIndex = uv_idx
                vg.colorIndex   = col_idx
                tri.vertex_groups.append(vg)

        # convert to triangle strips
        if use_triangle_strips:
            strip_primitives = triangles_to_strips(triangles)
        else:
            strip_primitives = triangles

        for prim in strip_primitives:
            face.primitives.append(prim)
        # set material indices
        for prim in strip_primitives:
            prim.set_material_index(get_material_index(hsf, poly.material))

    # Make mesh object
    obj = HsfObject()
    obj.name = name
    obj.type = HSF_OBJECT_TYPE.MESH
    obj.data = HsfObjectData()
    obj.data.vertexIndex = len(hsf.vertices)
    obj.data.normalIndex = len(hsf.normals)
    if len(uvs_buf.values) > 0:
        obj.data.texCoordIndex = len(hsf.tex_coords)
    if len(colors_buf.values) > 0:
        obj.data.colorIndex = len(hsf.colors)
    obj.data.faceIndex = len(hsf.faces) - 1
    if has_attributes:
        obj.data.attributeIndex = 0
    else:
        obj.data.attributeIndex = -1

    min_vertex, max_vertex = calculate_min_max(vertices)
    obj.data.min = min_vertex
    obj.data.max = max_vertex

    positions_buf.name = name
    normals_buf.name = name
    uvs_buf.name = name
    colors_buf.name = name

    hsf.vertices.append(positions_buf)
    if len(normals_buf.values) > 0:
        hsf.normals.append(normals_buf)
    if len(uvs_buf.values) > 0:
        hsf.tex_coords.append(uvs_buf)
    if len(colors_buf.values) > 0:
        hsf.colors.append(colors_buf)

    if len(morph_buffer) > 0:
        create_shapes(hsf, obj, morph_buffer)

  #  if len(morph_buffer) > 0:
    #    create_clusters(hsf, obj, morph_buffer)

    envelope = create_envelopes(pos_skin_map, name)
    if envelope:
        obj.data.envelopeIndex = len(hsf.envelopes)
        obj.data.envelopeCount = 1
        hsf.envelopes.append(envelope)
    elif has_envelopes:
        obj.data.envelopeIndex = len(hsf.envelopes)
        obj.data.envelopeCount = 1

        env = HsfEnvelope()
        env.vertexCount = len(positions_buf.values)
        hsf.envelopes.append(env)

    return obj

def create_shapes(hsf, obj, morph_buffer):
    # Base morph
    obj.data.shapeIndices.append(obj.data.vertexIndex)
    # Morph vertex buffer indices
    for buffer in morph_buffer:
        idx = len(hsf.vertices)
        hsf.vertices.append(buffer)
        obj.data.shapeIndices.append(idx)

    shape = HsfShape()
    hsf.shapes.append(shape)
    shape.name = obj.name
    shape.buffer = obj.data.shapeIndices

def create_clusters(hsf, obj, morph_buffer):
    num_verts = len(morph_buffer[0].values)

    obj.data.clusterIndices.append(len(hsf.clusters))

    # Cluster requires envelopes

    cluster = HsfCluster()
    hsf.clusters.append(cluster)

    cluster.target = obj.name
    cluster.name1 = obj.name
    cluster.name2 = obj.name
    cluster.partIdx = len(hsf.parts)
    cluster.type = 0 # 2 = multi weights[32] else single with baseMorph
    cluster.baseMorph = 2.0

    part = HsfPart()
    hsf.parts.append(part)

    for buffer in morph_buffer:
        idx = len(hsf.vertices)
        hsf.vertices.append(buffer)
        cluster.buffer.append(idx)
    # Set each vertex
    for i in range(num_verts):
        part.data.append(i)

def _get_consecutive_ranges(indices: list[int]) -> list[tuple[int, int]]:
    """Turn a list of position indices into (start, count) ranges."""
    if not indices:
        return []
    sorted_idx = sorted(set(indices))
    ranges = []
    start = sorted_idx[0]
    count = 1
    for i in range(1, len(sorted_idx)):
        if sorted_idx[i] == sorted_idx[i - 1] + 1:
            count += 1
        else:
            ranges.append((start, count))
            start = sorted_idx[i]
            count = 1
    ranges.append((start, count))
    return ranges

def create_envelopes(
    pos_skin_map: dict[int, Tuple[int, float], ...],
    mesh_name: str = "default"
) -> list[HsfEnvelope]:
    if not pos_skin_map:
        return None

    env = HsfEnvelope()
    env.name = mesh_name
    env.singleBinds = []
    env.doubleBinds = []
    env.multiBinds = []
    env.singleBindCount = 0
    env.doubleBindCount = 0
    env.multiBindCount = 0
    env.vertexCount = len(pos_skin_map) # same as vertex count
    env.copyCount = 0 # set at runtime

    # Group by exact skin configuration
    skin_groups: dict[Tuple[Tuple[int, float], ...], list[int]] = defaultdict(list)
    for pos_idx, skin in pos_skin_map.items():
        if not skin:  # no skin data
            continue
        skin_groups[skin].append(pos_idx)

    for skin_tuple, pos_list in skin_groups.items():
        ranges = _get_consecutive_ranges(pos_list)
        num_bones = len(skin_tuple)

        if num_bones == 1: # 1 bone
            bone, _ = skin_tuple[0]
            for start, count in ranges:
                sb = HsfEnvelopeSingle()
                sb.boneIndex = bone
                sb.positionIndex = start
                sb.positionCount = count
                sb.normalIndex = start
                sb.normalCount = count
                env.singleBinds.append(sb)
        elif num_bones == 2: # 1 bone
            (bone1, w1), (bone2, w2) = skin_tuple
            db = HsfEnvelopeDouble()
            db.bone1 = bone1
            db.bone2 = bone2
            db.weights = []
            for start, count in ranges:
                dw = HsfEnvelopeDoubleWeight()
                dw.weight = w1 #(bone2 = 1.0 - w1)
                dw.positionIndex = start
                dw.positionCount = count
                dw.normalIndex = start
                dw.normalCount = count
                db.weights.append(dw)
            db.weightCount = len(db.weights)
            env.doubleBinds.append(db)
        else:
            # (3+ bones)
            for start, count in ranges:
                mb = HsfEnvelopeMultiBind()
                mb.weightCount = num_bones
                mb.positionIndex = start
                mb.positionCount = count
                mb.normalIndex = start
                mb.normalCount = count
                mb.weights = []
                for bone, weight in skin_tuple:
                    mw = HsfEnvelopeMultiBindWeight()
                    mw.boneIndex = bone
                    mw.weight = weight
                    mb.weights.append(mw)
                env.multiBinds.append(mb)
    return env

def calculate_min_max(vertices:List[Vertex]):
    min_x, min_y, min_z = float('inf'), float('inf'), float('inf')
    max_x, max_y, max_z = float('-inf'), float('-inf'), float('-inf')
    for vert in vertices:
        x, y, z = vert.position
        min_x = min(min_x, x);  min_y = min(min_y, y);  min_z = min(min_z, z)
        max_x = max(max_x, x);  max_y = max(max_y, y);  max_z = max(max_z, z)
    return ((min_x, min_y, min_z), (max_x, max_y, max_z))

def maxBitVal(numBits: int):
    """Return the maximum value possible for a value stored in some number of bits."""
    return (1 << numBits) - 1

def triangles_to_strips(triangles: list[HsfFacePrimitive]):
    # tuple of triangle
    all_tri_vgs: list[tuple[HsfVertexGroup, HsfVertexGroup, HsfVertexGroup]] = []
    for prim in triangles:
        all_tri_vgs.append(tuple(prim.vertex_groups))

    def vg_key(vg: HsfVertexGroup) -> tuple[int, int, int, int]:
        return (vg.positionIndex, vg.normalIndex, vg.texCoordIndex, vg.colorIndex)

    unique_vgs: list[HsfVertexGroup] = []
    vg_to_index: dict[tuple[int, int, int, int], int] = {}

    for tri in all_tri_vgs:
        for vg in tri:
            key = vg_key(vg)
            if key not in vg_to_index:
                vg_to_index[key] = len(unique_vgs)
                unique_vgs.append(vg)

    tri_indices: list[tuple[int, int, int]] = []
    for tri in all_tri_vgs:
        i0 = vg_to_index[vg_key(tri[0])]
        i1 = vg_to_index[vg_key(tri[1])]
        i2 = vg_to_index[vg_key(tri[2])]
        tri_indices.append((i0, i1, i2))

    strips = calc_tristrip(tri_indices, maxBitVal(16))

    result: list[HsfFacePrimitive] = []
    for strip in strips:
        if len(strip) < 3:
            continue

        prim = HsfFacePrimitive()

        if len(strip) == 3:
            # Make as triangle
            prim.type = HSF_PRIMITIVE_TYPE.TRIANGLE
            for local_idx in strip:
                prim.vertex_groups.append(unique_vgs[local_idx])
        else:
            v0 = unique_vgs[strip[0]]
            v1 = unique_vgs[strip[1]]
            v2 = unique_vgs[strip[2]]
            continuation = [unique_vgs[i] for i in strip[3:]]

            merged = [v0, v1, v2, v1] + continuation

            prim.type = HSF_PRIMITIVE_TYPE.TRIANGLE_STRIP
            prim.vertex_groups = merged

        result.append(prim)

    return result

