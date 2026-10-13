from . hsf_file import *

class GXDrawMesh:
    def __init__(self):
        self.drawCalls:List[DrawCall] = []
        self.vertices:List[DrawVertex] = []
        self.indices:List[int] = []
        self.totalIndexCount = 0

class GXDrawVertex:
    def __init__(self):
        self.position = (0.0, 0.0, 0.0)
        self.normal = (0.0, 1.0, 0.0)
        self.tex_coord = (0.0, 0.0)
        self.color = (1.0, 1.0, 1.0, 1.0)
        self.weights = [] # list of tuple (index, weight)

class GXDrawCall:
    def __init__(self):
        self.prim_type:int = 0
        self.vertex_count:int = 0

def convert_gx_meshes(hsf, obj):
    """
    Converts hsf mesh data into standard mesh data with vertices and triangle indices.
    Returns a dictionary of meshes divided by their material indices.
    """
    hsf_mesh = obj.data
    face_data = hsf.faces[hsf_mesh.faceIndex]
    # position buffer
    vertices = hsf.vertices[hsf_mesh.vertexIndex].values
    # normal buffer
    if hsf_mesh.normalIndex != -1 and len(hsf.normals) > hsf_mesh.normalIndex:
        normals = hsf.normals[hsf_mesh.normalIndex].values
    # uvs buffer
    if hsf_mesh.texCoordIndex != -1 and len(hsf.tex_coords) > hsf_mesh.texCoordIndex:
        tex_coords = hsf.tex_coords[hsf_mesh.texCoordIndex].values
    # colors buffer
    if hsf_mesh.colorIndex != -1 and len(hsf.colors) > hsf_mesh.colorIndex:
        colors = hsf.colors[hsf_mesh.colorIndex].values
    # envelopes
    vertex_single_bind = None
    vertex_skinning = {}
    if hsf_mesh.envelopeIndex != -1 and len(hsf.envelopes) > hsf_mesh.envelopeIndex:
        for env_idx in range(hsf_mesh.envelopeCount):
            envelope = hsf.envelopes[env_idx + hsf_mesh.envelopeIndex]
            vertex_skinning = {} # vertex pos then array tuple of index + weight
            # Single binds
            for bind in envelope.singleBinds:
                for v in range(bind.positionCount):
                    vertex_skinning[bind.positionIndex + v] = [(bind.boneIndex, 1.0)]
            # Double binds
            for bind in envelope.doubleBinds:
                for w in bind.weights:
                    for v in range(w.positionCount):
                        vertex_skinning[w.positionIndex + v] = [(bind.bone1, w.weight), (bind.bone2, 1.0 - w.weight)]
            # Multi binds
            for bind in envelope.multiBinds:
                for v in range(bind.positionCount):
                    weight_list = []
                    for w in bind.weights:
                        weight_list.append((w.boneIndex, w.weight))
                    vertex_skinning[bind.positionIndex + v] = weight_list
            # If skinning is empty, it uses single binds
            vertex_single_bind = obj.index

	# Map each primitive to lookup by material
    material_mapper = {}

    for prim in face_data.primitives:
        mat = prim.get_material_index()
        if mat not in material_mapper:
            material_mapper[mat] = GXDrawMesh()

        mesh = material_mapper[mat]

        # store draw info for triangle calculations afterward
        draw = GXDrawCall()
        draw.prim_type = prim.type
        mesh.drawCalls.append(draw)

        if prim.type == HSF_PRIMITIVE_TYPE.TRIANGLE:
            indexCount = len(prim.vertex_groups) - 1;
            vertexCount = len(prim.vertex_groups) - 1;
        elif prim.type == HSF_PRIMITIVE_TYPE.TRIANGLE_STRIP:
            indexCount = (len(prim.vertex_groups) - 2) * 3;
            vertexCount = len(prim.vertex_groups);
        elif prim.type == HSF_PRIMITIVE_TYPE.QUAD:
            indexCount = ((len(prim.vertex_groups) * 6) / 4) * 3;
            vertexCount = len(prim.vertex_groups);

        mesh.totalIndexCount += indexCount;
        draw.vertex_count = vertexCount;

        for v in range(vertexCount):
            vg = prim.vertex_groups[v]

            vert = GXDrawVertex()
            mesh.vertices.append(vert)

            vert.position = vertices[vg.positionIndex]
            if vg.normalIndex != -1:
                vert.normal = normals[vg.normalIndex]
            if vg.texCoordIndex != -1:
                vert.tex_coord = tex_coords[vg.texCoordIndex]
            if vg.colorIndex != -1:
                vert.color = colors[vg.colorIndex]

            if vertex_skinning and vg.positionIndex in vertex_skinning:
                vert.weights = vertex_skinning[vg.positionIndex]
                print(f"{vg.positionIndex} weights {vert.weights}")
            elif vertex_single_bind:
                vert.weights = [(vertex_single_bind, 1.0)]

    for mat_idx, mesh in material_mapper.items():
        mesh.indices = generate_indices(mesh.drawCalls, int(mesh.totalIndexCount), 0, len(mesh.vertices));

    return material_mapper

def generate_indices(draw_calls, total_index_count, first_vertex_id, vertexCount):
    dst_idx = 0
    dst = [0] * total_index_count
    base_vertex = first_vertex_id

    for draw_call in draw_calls:
        prim = draw_call.prim_type
        vcnt = draw_call.vertex_count

        if prim == HSF_PRIMITIVE_TYPE.TRIANGLE:
            for i in range(vcnt):
                dst[dst_idx] = base_vertex + i
                dst_idx += 1
            base_vertex += vcnt
        elif prim == HSF_PRIMITIVE_TYPE.TRIANGLE_STRIP:
            for i in range(2, vcnt):
                dst[dst_idx    ] = base_vertex + i - 2
                dst[dst_idx + 1] = base_vertex + i - (~i & 1)
                dst[dst_idx + 2] = base_vertex + i - (i & 1)
                dst_idx += 3
            base_vertex += vcnt
        elif prim == HSF_PRIMITIVE_TYPE.QUAD:
            for _ in range(0, draw_call.vertex_count, 4):
                # triangle 1: v0, v1, v2
                dst[dst_idx]     = base_vertex + 0
                dst[dst_idx + 1] = base_vertex + 1
                dst[dst_idx + 2] = base_vertex + 2
                # triangle 2: v1, v3, v2
                dst[dst_idx + 3] = base_vertex + 1
                dst[dst_idx + 4] = base_vertex + 3
                dst[dst_idx + 5] = base_vertex + 2
                dst_idx += 6
                base_vertex += 4

    return to_valid_indices(dst, vertexCount)

def to_valid_indices(indices, vertexCount):
    out_indices: List[int] = []
    for i in range(0, len(indices), 3):
        a, b, c = indices[i], indices[i + 1], indices[i + 2]
        if (a == b == c):
            continue
        if a >= vertexCount or b >= vertexCount or c >= vertexCount:
            print(f"bad triangle indices {a} {b} {c} vertexCount {vertexCount}")
            continue

        out_indices.append(a)
        out_indices.append(b)
        out_indices.append(c)
    return out_indices

def _is_valid_triangle(a: int, b: int, c: int, vertex_count: int) -> bool:
    if a >= vertex_count or b >= vertex_count or c >= vertex_count:
        return False
    if a == b == c:
        return False
    return True

# Direct port of https://github.com/hayden0729/berrybush/blob/main/berrybush/wii/gx.py#L1815
# Used for tri strip creation

def calc_tristrip(tris: list[tuple[int, int, int]], maxLen: int = None):
    """Convert triangles (tuples w/ 3 vertex indices) to strips (lists of vertex indices)."""
    # this is a basic implementation that pretty much makes random lines until it can't anymore
    # the result's not too shabby though!
    strips: list[list[int]] = []
    edgeAdjacentVerts: dict[tuple[int, int], list[int]] = {}
    # create map from edges to the all their adjacent vertices
    for tri in tris:
        edgeAdjacentVerts.setdefault((tri[0], tri[1]), []).append(tri[2])
        edgeAdjacentVerts.setdefault((tri[1], tri[2]), []).append(tri[0])
        edgeAdjacentVerts.setdefault((tri[2], tri[0]), []).append(tri[1])
    # create strips by picking arbitrary starting points and then going down arbitrary paths
    while edgeAdjacentVerts:
        firstEdge, firstEdgeAdjacentVerts = edgeAdjacentVerts.popitem() # pop to get edge fast
        edgeAdjacentVerts[firstEdge] = firstEdgeAdjacentVerts # add back so item isn't removed
        strip = list(firstEdge)
        strips.append(strip)
        expandTristrip(strip, edgeAdjacentVerts, maxLen)
        # after initial strip expansion, expand it in the opposite direction as well
        # to do this, reverse the strip, then expand it
        # then, if reversing flipped the faces (which happens if the strip has an odd length),
        # we have to flip them back by adding an extra vert to the beginning
        # isFlipped = len(strip) % 2
        # strip.reverse()
        # expandTristrip(strip, edgeAdjacentVerts, maxLen, isReversed=True)
        # if isFlipped:
        #     if len(strip) % 2:
        #         strip.reverse()
        #     else:
        #         strip.insert(0, strip[0]) # reverse doesn't flip faces; only way is extra vert
        # COMMENTED OUT FOR NOW BECAUSE THE INSERTION IN THE LINE ABOVE MAKES REVERSING NOT
        # WORTH IT (compression gains are balanced out by the extra vertices)
    return strips


def expandTristrip(strip: list[int], edgeAdjacentVerts: dict[tuple[int, int], list[int]],
                   maxLen: int = None, isReversed = False):
    """Expand a triangle strip forwards until it can't be expanded anymore."""
    # order alternates with every entry (clockwise vs counter)
    # isReversed determines which order to start with
    doReverse = isReversed
    latestEdge = tuple(strip[-2:])
    noMaxLen = maxLen is None
    while latestEdge in edgeAdjacentVerts and (noMaxLen or len(strip) < maxLen):
        adjacentVerts = edgeAdjacentVerts[latestEdge]
        newVert = adjacentVerts.pop() # pop one vert adjacent to this edge
        strip.append(newVert)
        tri = (*latestEdge, newVert) * 2
        for edgeIdx in range(1, 3):
            # in addition to deleting the data for this edge, delete the data for
            # equivalent edges/adjacent verts
            # for instance, the tri (1, 2, 3) will have an entry for (1, 2) to 3,
            # (2, 3) to 1, and (3, 1) to 2; if we're looking at the (1, 2) edge, the
            # other entries will still need to be popped as well since they represent
            # the same tri
            offsetEdge = tri[edgeIdx : edgeIdx + 2]
            offsetAdjacentVerts = edgeAdjacentVerts[offsetEdge]
            offsetAdjacentVerts.remove(tri[edgeIdx + 2])
            if not offsetAdjacentVerts:
                del edgeAdjacentVerts[offsetEdge]
        if not adjacentVerts:
            try:
                del edgeAdjacentVerts[latestEdge]
            except KeyError:
                # we can only get here if the entry for this edge was deleted in the above loop,
                # i.e., two of this triangle's edges are the same
                # (i.e., the triangle is actually just a line)
                pass
        doReverse = not doReverse
        latestEdge = tuple(strip[-2:][::-1]) if doReverse else tuple(strip[-2:])