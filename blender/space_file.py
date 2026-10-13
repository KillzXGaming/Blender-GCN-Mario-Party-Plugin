from . io_util import *
import csv
import bpy
import bmesh
import io

class Space():
    def __init__(self):
        self.position = (0, 0, 0)
        self.rotation = (0, 0, 0)
        self.scale = (0, 0, 0)
        self.flags = 0
        self.flags_ex = 0 # MP6 and later, 16 more bits
        self.type = 0
        self.links = []
        self.name = "" # blender specific

    @classmethod
    def load(cls, filePath):
        with open(filePath, 'rb') as f:
            reader = BinaryReader(f, endian=">")
            return read(reader, isVersion2)

def load_raw(data: bytes, isVersion2 = False):
    with io.BytesIO(data) as f:
        return read(BinaryReader(f, ">"), isVersion2)

def load(filePath, isVersion2 = False):
    with open(filePath, 'rb') as f:
        read(BinaryReader(f, ">"), isVersion2)

def read(r, isVersion2 = False):
    spaces = []
    num_spaces = r.read_u32()
    for _ in range(num_spaces):
        space = Space()
        spaces.append(space)

        space.position = r.read_vec3()
        space.rotate = r.read_vec3()
        space.scale = r.read_vec3()
        space.flags = r.read_i32()
        # Version 2 (MP6+) adds extra 16 bits for flags
        if isVersion2:
            space.flags_ex = r.read_i16()
        space.type = r.read_i16()
        num_links = r.read_u16()
        for l in range(num_links):
            space.links.append(r.read_u16())

    return spaces

def write(spaces, filePath, isVersion2 = False):
    with open(filePath, 'wb') as f:
        w = BinaryWriter(f, ">")

        w.write_u32(len(spaces))
        for space in spaces:
            w.write_vec3(space.position)
            w.write_vec3(space.rotate)
            w.write_vec3(space.scale)
            w.write_i32(space.flags)
            # Version 2 (MP6+) adds extra 16 bits for flags
            if isVersion2:
                w.write_i16(space.flags_ex)
            w.write_i16(space.type)
            w.write_u16(len(space.links))
            for link in space.links:
                w.write_u16(link)

        return spaces

def save_as_csv(spaces, filePath, isVersion2 = False):
    header = [ 
        'name',
        'position_x', 'position_y', 'position_z',
        'rotate_x',   'rotate_y',   'rotate_z',
        'scale_x',    'scale_y',    'scale_z',
        'flags', 
    ]
    if isVersion2:
        header.append('flags_ex') 

    header.extend([
        'type',
        'links'
    ])

    with open(filePath, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file, delimiter=',')
        writer.writerow(header)

        for i, sp in enumerate(spaces):
            row = [
                sp.name if sp.name != "" else f"Point{i}",
                sp.position[0], sp.position[1], sp.position[2],
                sp.rotate[0],   sp.rotate[1],   sp.rotate[2],
                sp.scale[0],    sp.scale[1],    sp.scale[2],
                sp.flags,
            ]

            if isVersion2:
                row.append(sp.flags_ex if sp.flags_ex is not None else 0)

            row.extend([
                sp.type,
                ';'.join(str(l) for l in sp.links)
            ])

            writer.writerow(row)

def convert_to_blender(context, spaces):
    # Use mesh vertices so we can add custom attributes
    mesh_data = bpy.data.meshes.new(name="PartyPath")

    verts = []
    edges = []
    for i, space in enumerate(spaces):
        # Y to Z up
        verts.append((space.position[0], -space.position[2], space.position[1]))

        for link in space.links:
            edges.append((i, link))

    mesh_data.from_pydata(verts, edges, [])
    mesh_data.update()

    mesh_data.attributes.new(name="Flags", type='INT', domain='POINT')
    mesh_data.attributes.new(name="FlagsEx", type='INT', domain='POINT')
    mesh_data.attributes.new(name="Type", type='INT', domain='POINT')
    mesh_data.attributes.new(name="Scale", type='FLOAT_VECTOR', domain='POINT')
    mesh_data.attributes.new(name="Rotate", type='FLOAT_VECTOR', domain='POINT')
    mesh_data.attributes.new(name="Direction", type='BOOLEAN', domain='EDGE')

    forward_attr = mesh_data.attributes["Direction"]
    for i in range(len(mesh_data.edges)):
        forward_attr.data[i].value = False

    flags_attr = mesh_data.attributes["Flags"]
    flagsex_attr = mesh_data.attributes["FlagsEx"]
    type_attr = mesh_data.attributes["Type"]
    scale_attr = mesh_data.attributes["Scale"]
    rotate_attr = mesh_data.attributes["Rotate"]

    for i, space in enumerate(spaces):
        flags_attr.data[i].value = int(space.flags)
        flagsex_attr.data[i].value = int(space.flags_ex)
        type_attr.data[i].value = int(space.type)
        scale_attr.data[i].vector = (space.scale[0], space.scale[2], space.scale[1])
        rotate_attr.data[i].vector = (space.rotate[0], space.rotate[2], -space.rotate[1])

    # Add path object
    obj = bpy.data.objects.new("PartyPath", mesh_data)
    context.collection.objects.link(obj)

    obj["branch_path_draw"] = True

    # Make active
    obj.select_set(True)
    context.view_layer.objects.active = obj

    # force refresh
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()
    pass

def convert_from_blender(context, obj = None):
    # Use active object unless specific path is set
    if not obj:
        obj = context.active_object
    mesh = obj.data

    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(mesh)
        verts = bm.verts
        edges = bm.edges
        use_bmesh = True
        layer_direction = bm.edges.layers.bool.get("Direction")
        layer_space_type = bm.verts.layers.int.get("Type")
        layer_flags = bm.verts.layers.int.get("Flags")
        layer_scale = bm.verts.layers.float_vector.get("Scale")
        layer_rotate = bm.verts.layers.float_vector.get("Rotate")

        edge_direction = lambda e: bool(e[layer_direction]) 
        get_space_type = lambda e: int(e[layer_space_type]) 
        get_scale = lambda e: list(e[layer_scale]) 
        get_rotate = lambda e: list(e[layer_rotate]) 
        get_flags = lambda e: int(e[layer_flags]) 
    else:
        direction_attr = mesh.attributes.get("Direction")
        type_attr = mesh.attributes.get("Type")
        scale_attr = mesh.attributes.get("Scale")
        rotate_attr = mesh.attributes.get("Rotate")
        flags_attr = mesh.attributes.get("Flags")
        use_bmesh = False

        verts = mesh.vertices
        edges = mesh.edges
        edge_direction = lambda e: direction_attr.data[e.index].value
        get_space_type = lambda e: type_attr.data[e.index].value
        get_scale = lambda e: scale_attr.data[e.index].vector
        get_rotate = lambda e: rotate_attr.data[e.index].vector
        get_flags = lambda e: flags_attr.data[e.index].value

    spaces = []
    for i, vert in enumerate(verts):
        local_pos = vert.co if use_bmesh else vert.co
        position = obj.matrix_world @ local_pos
        scale = get_scale(vert)
        rotate = get_rotate(vert)
        space_type = get_space_type(vert)
        flags = get_flags(vert)

        space = Space()
        # Z up to Y up
        space.position = (position[0], position[2], -position[1])
        space.scale = (scale[0], scale[2], scale[1])
        space.rotate = (rotate[0], -rotate[2], rotate[1])
        space.type = int(space_type)
        space.flags = int(flags)
        space.flags_ex = 0
        spaces.append(space)

    for edge in edges:
        if use_bmesh:
            idx0 = edge.verts[0].index
            idx1 = edge.verts[1].index
        else:
            idx0 = edge.vertices[0]
            idx1 = edge.vertices[1]

        backward = edge_direction(edge)
        if backward: 
            spaces[idx1].links.append(idx0)
        else: 
            spaces[idx0].links.append(idx1)

    return spaces