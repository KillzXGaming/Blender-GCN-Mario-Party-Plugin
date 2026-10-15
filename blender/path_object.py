import bpy, gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
import math
import bmesh
import ctypes
import json
from bpy_extras.io_utils import ExportHelper, ImportHelper
from bpy.props import *
from bpy.app.handlers import persistent
from . import space_file
from . import path_flags
from . import game_config
import os
from . import blender_import
from ..hsf import hsf_file
from ..hsf import bin_mp

from . mesh_utils import get_or_create_attributes_float_vector, get_or_create_attributes_float, get_or_create_attributes_int

selected_index = -1

def set_attributes(context):
    """
    Applies the current blender UI properties attached 
    to the mesh to the currently selected point attributes.
    Must be in edit mode for these to apply.
    """

    scene = context.scene
    obj = context.active_object
    mesh = obj.data
    flags = mesh.party_properties.Flags
    flags2 = mesh.party_properties.FlagsExtra
    space_type = mesh.party_properties.SpaceTypeId
    scale = mesh.party_properties.Scale
    rotate = mesh.party_properties.Rotate

    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(mesh)
        flags_layer = get_or_create_attributes_int(mesh, bm, "Flags")
        flagsex_layer = get_or_create_attributes_int(mesh, bm, "FlagsEx")
        type_layer = get_or_create_attributes_int(mesh, bm, "Type")
        scale_layer = get_or_create_attributes_float_vector(mesh, bm, "Scale")
        rotate_layer = get_or_create_attributes_float_vector(mesh, bm, "Rotate")

        sel_vertices = [e for e in bm.verts if e.select]
        for vert in sel_vertices:
            vert[flags_layer] = int(flags)
            vert[flagsex_layer] = int(flags2)
            vert[type_layer] = int(space_type)
            vert[scale_layer] = scale
            vert[rotate_layer] = rotate
            


def get_or_create_attributes_int(mesh, bm, attr_name):
    flags = bm.verts.layers.int.get(attr_name)
    if not flags:
        flags = mesh.attributes.new(name=attr_name, type='INT', domain='POINT')
    return flags

@persistent
def depsgraph_update_post(scene, depsgraph):
    """
    Runs after every depsgraph update.
    Checks for selection changes and ensure to set the active property UI based on the selected path point.
    """
    if bpy.context.active_object is None:
        return

    for update in depsgraph.updates:
        if not isinstance(update.id, bpy.types.Object):
            continue

        obj = bpy.context.active_object
        # Todo the update.id instance does not apply the properties, use active obj for now
        if obj.name != update.id.name or obj.mode != 'EDIT':
            continue
        # Ensure the party path mesh is being edited
        if obj.type != 'MESH' or not obj.get("branch_path_draw", False):
            continue

        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        sel_vertices = [e for e in bm.verts if e.select]
        if sel_vertices:
            previous_select = mesh.party_properties.selected_index
            if len(sel_vertices) >= 1:
                mesh.party_properties.selected_index = sel_vertices[0].index
            else:
                mesh.party_properties.selected_index = -1

            # Selection changed
            if previous_select != mesh.party_properties.selected_index:
                # Check direction
                layer = bm.edges.layers.bool.get("Direction")

        if sel_vertices:
            first_vert = sel_vertices[0]
            # We want to set the currently selected flag value
            flags_layer = get_or_create_attributes_int(mesh, bm, "Flags")
            flagsex_layer = get_or_create_attributes_int(mesh, bm, "FlagsEx")
            type_layer = get_or_create_attributes_int(mesh, bm, "Type")
            scale_layer = get_or_create_attributes_float_vector(mesh, bm, "Scale")
            rotate_layer = get_or_create_attributes_float_vector(mesh, bm, "Rotate")

            # party_properties = PartyPathPointProps
            # Supress set_attributes as we only want that updated during manual user edits
            mesh.party_properties.attributes_update = False

            flags1 = first_vert[flags_layer]
            flags2 = first_vert[flagsex_layer]
            scale = first_vert[scale_layer]
            rotate = first_vert[rotate_layer]

            mesh.party_properties.Flags = int(flags1)
            mesh.party_properties.FlagsExtra = int(flags2)
            mesh.party_properties.Scale = (scale[0], scale[1], scale[2])
            mesh.party_properties.Rotate = (rotate[0], rotate[1], rotate[2])

            mesh.party_properties.SpaceTypeId = int(first_vert[type_layer])
            mesh.party_properties.attributes_update = True

_DYNAMIC_PANELS = []

def register_dynamic_properties():
    print("register_dynamic_properties")

    games = game_config.load(force=True)
    if not games:
        return

    # __annotations__ to store dynamic properties
    if not hasattr(PartyPathPointProps, "__annotations__"):
        PartyPathPointProps.__annotations__ = {}

    panel_cls = path_flags.DynamicCategoryPanel
    bpy.utils.register_class(panel_cls)
    _DYNAMIC_PANELS.append(panel_cls)

    PartyPathPointProps.__annotations__["dummy"] = BoolProperty(default = False)

    # Flag properties are registered for every game using a game specific id (see
    # game_config.flag_prop_id). The panel only draws the ones of the active game.
    for game_json in games:
        for flag_json in game_json["flags"]:
            prop_id = flag_json["_prop_id"]
            prop = path_flags.make_prop(prop_id, flag_json, game_json["enums"])

            if prop:
                PartyPathPointProps.__annotations__[prop_id] = prop


def unregister():
    for c in reversed(_DYNAMIC_PANELS):
        bpy.utils.unregister_class(c)
    _DYNAMIC_PANELS.clear()

class GameSettings(bpy.types.PropertyGroup):
    name: StringProperty(
        name="Name"
    )

def load_game_list():
    game_list = bpy.context.scene.party_properties.game_list
    game_list.clear()

    for game_json in game_config.load():
        game_name = game_json["name"]

        print(f"game_name {game_name}")

        game = game_list.add()
        game.name = game_name

class PartyPathPointProps(bpy.types.PropertyGroup):
    attributes_update: BoolProperty(default=True)
    updating_flag_props: BoolProperty(default=False)
    updating_flags: BoolProperty(default=False)
    selected_index: IntProperty(default=-1)
    edge_hash: IntProperty(default=-1)
    vert_hash: IntProperty(default=-1)

    def on_updated(self, context):
        # Update the attribute data if currently allowed
        # This is toggled off during UI set from point selection
        if self.attributes_update:
            set_attributes(context)

    game_items = [
        ("MP4", "Mario Party 4", "", "", 0),
        ("MP5", "Mario Party 5", "", "", 1),
        ("MP6", "Mario Party 6", "", "", 2),
        ("MP7", "Mario Party 7", "", "", 3),
        ("MP8", "Mario Party 8", "", "", 4),
    ]

    def on_game_updated(self, context):
        return

    def sync_flag_properties(self):
        """Sets the json flag properties of the active game from the current Flags value."""
        game_json = game_config.get_game(self.get_active_index())
        if game_json is None:
            return

        self.updating_flags = True
        try:
            for flag_json in game_json["flags"]:
                path_flags.set_flag_property(flag_json, self)
        finally:
            self.updating_flags = False

    def on_flags_updated(self, context):
        self.on_updated(context)
        if self.updating_flag_props:
            return

        # Set bit propery
        i = 0;
        for i in range(16):
            self.flagBits1[i] = path_flags.get_bits_i32(self.Flags, i + 1, 1)
        i = 0;
        for i in range(16):
            self.flagBits2[i] = path_flags.get_bits_i32(self.Flags, i  + 1+ 15, 1)

        # Set flag properties with new values
        self.sync_flag_properties()

    Flags : IntProperty(name="Flags", update=on_flags_updated)
    def on_flags_extra_updated(self, context):
        self.on_updated(context)
        if self.updating_flag_props:
            return
        # json flags with "field": "flags_ex" read from this value
        self.sync_flag_properties()

    FlagsExtra : IntProperty(name="Flags Extra", update=on_flags_extra_updated)
    # The type id stored on the point. SpaceType is only a dropdown view of it.
    SpaceTypeId : IntProperty(name="Type ID", description="Space type id stored on the point", default=0, update=on_updated)

    def _space_type_items(self, context):
        return game_config.space_type_enum_items(self.get_active_index(), self.SpaceTypeId)

    def _get_space_type(self):
        return self.SpaceTypeId

    def _set_space_type(self, value):
        self.SpaceTypeId = value

    # Items come from space_types of the active game in UI.json, the enum number is the type id.
    SpaceType : EnumProperty(name="Type", items=_space_type_items, get=_get_space_type, set=_set_space_type)
    Scale: FloatVectorProperty(name="Scale", size=3, default=[1, 1, 1], update=on_updated)
    Rotate: FloatVectorProperty(name="Rotate Euler Degrees", size=3, default=[0, 0, 0], update=on_updated)
   
    def _game_enum_items(self, context):
        return game_config.game_enum_items()

    def _set_game_from_index(self, context):
        # Flag properties and space types shown depend on the game
        self.sync_flag_properties()
        screen = getattr(context, "screen", None)
        if screen:
            for area in screen.areas:
                area.tag_redraw()

    def get_active_index(self):
        return game_config.clamp_game_index(self.SelectedGameIndex)
    def set_active_index(self, value):
        self.SelectedGameIndex = value

    ActiveGame: PointerProperty(name="Active Game", type=GameSettings)
    ActiveGameEnum : EnumProperty(
        name="Game",
        description="Pick which game to apply space settings to.",
        items=_game_enum_items,
        update=_set_game_from_index,
        get=get_active_index,
        set=set_active_index,
    )
    SelectedGameIndex: bpy.props.IntProperty(default=0) 

    # For optionally manually toggling flag bits
    flagBits1: bpy.props.BoolVectorProperty(
        name="Flag Bits [0-15]",
        default=[False] * 16,
        size=16,
        options=set()
    )
    flagBits2: bpy.props.BoolVectorProperty(
        name="Flag Bits [16-31]",
        default=[False] * 16,
        size=16,
        options=set()
    )
    # MP6-MP8 have 16 more bits from flags extra
    flagBits3: bpy.props.BoolVectorProperty(
        name="Flag Bits [32-47]",
        default=[False] * 16,
        size=16,
        options=set()
    )

    def get_sprite_index(self, space_type, flags):
        return game_config.get_sprite_index(self.get_active_index(), space_type, flags)

    def get_value(self, item_name):
        prop_id = path_flags.get_property_id(item_name)
        return getattr(self, prop_id, None)

    def set_value(self, item_name, value):
        prop_id = path_flags.get_property_id(item_name)
        if hasattr(self, prop_id):
            setattr(self, prop_id, value)

    def is_valid(self, item_name, value):
        prop_id = path_flags.get_property_id(item_name)
        if hasattr(self, prop_id):
            prop = self.bl_rna.properties[prop_id]
            if prop.type == 'ENUM':
                valid_ids = {item.identifier for item in prop.enum_items}
                print(str(valid_ids))
                return value in valid_ids
        return True

class OBJECT_OT_change_edge_direction(bpy.types.Operator):
    """Swaps the direction of the selected edges to the inverse of what it is set to."""
    bl_idname = "object.change_edge_direction"
    bl_label = "Change Direction"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Active object is not a mesh")
            return {'CANCELLED'}

        if obj.mode != 'EDIT':
            self.report({'WARNING'}, "Must be in Edit‑Mode")
            return {'CANCELLED'}

        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        layer = bm.edges.layers.bool.get("Direction")
        if layer is None:
            self.report({'INFO'}, "No direction attribute detected!")
            return {'CANCELLED'}

        # selected edges
        selected_edges = [e for e in bm.edges if e.select]

        if not selected_edges:
            self.report({'INFO'}, "No edges selected")
            return {'CANCELLED'}

        # set to the inverse setting
        for e in selected_edges:
            e[layer] = not e[layer]

        bmesh.update_edit_mesh(mesh)

        return {'FINISHED'}

class OBJECT_PT_party_path(bpy.types.Panel):
    """Tool panel for the selected party path point properties."""
    bl_label = "Party Path"
    bl_idname = "OBJECT_PT_party_path"
    bl_space_type = 'VIEW_3D' 
    bl_region_type = 'UI'
    bl_category   = "Item" 

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'MESH' and obj.get("branch_path_draw", False)

    def draw(self, context):
        layout = self.layout
        obj = context.object
        mesh = obj.data

        layout.prop(mesh.party_properties, "ActiveGameEnum")           

        if obj.mode != 'EDIT':
            layout.label(text="Go into edit mode to configure.", icon='INFO')
            return

        bm = bmesh.from_edit_mesh(mesh)
        layer = bm.edges.layers.bool.get("Direction")
        if layer is None:
            layout.label(text="Failed to find direction attribute!", icon='INFO')
            return

        if not hasattr(obj.data, "party_properties"):
            return

        sel_vertices = [e for e in bm.verts if e.select]
        if sel_vertices:
            first = sel_vertices[0]

            row = layout.row()
            row.label(text=f"Selected Point # {first.index}")
            # SpaceType
            row = layout.row(align=True)
            row.label(text="Space Type")
            row.prop(mesh.party_properties, "SpaceType", text="")
            id_row = row.row(align=True)
            id_row.scale_x = 0.5
            id_row.prop(mesh.party_properties, "SpaceTypeId", text="")
            # Scale
            row = layout.row(align=True)
            row.label(text="Scale")
            row.prop(mesh.party_properties, "Scale", text="")   
            # Rotate
            row = layout.row(align=True)
            row.label(text="Rotate")
            row.prop(mesh.party_properties, "Rotate", text="")

        sel_edges = [e for e in bm.edges if e.select]
        if sel_edges:
            first = sel_edges[0]
            cur_val = bool(first[layer])
            row = layout.row()
            row.label(text=f"Selected Edge # {first.index}")
            row = layout.row()
            row.operator("object.change_edge_direction", icon='ARROW_LEFTRIGHT')

class OBJECT_OT_import_spaces_mp4to5(bpy.types.Operator, ImportHelper):
    """Import spaces from a bin file for mario party 4 - 5."""
    bl_idname = "object.import_spaces"
    bl_label = "Import Spaces (MP4-MP5)"    
    bl_options   = {'PRESET', 'UNDO'}

    filename_ext = ".bin"
    filter_glob: StringProperty(
        default="*.bin;",
        options={'HIDDEN'},
    )
    def execute(self, context):

        binf = bin_mp.BinFile.load(self.filepath)
        isVersion2 = False
        spaces = space_file.load_raw(binf.files[0].data, isVersion2)
        space_file.convert_to_blender(context, spaces)
        return {'FINISHED'}

class OBJECT_OT_import_spaces_mp6to8(bpy.types.Operator, ImportHelper):
    """Import spaces from a bin file for mario party 6 - 8."""
    bl_idname = "object.import_spaces68"
    bl_label = "Import Spaces (MP6-MP8)"    
    bl_options   = {'PRESET', 'UNDO'}

    filename_ext = ".bin"
    filter_glob: StringProperty(
        default="*.bin;",
        options={'HIDDEN'},
    )
    def execute(self, context):

        binf = bin_mp.BinFile.load(self.filepath)
        isVersion2 = True
        spaces = space_file.load_raw(binf.files[0].data, isVersion2)
        space_file.convert_to_blender(context, spaces)
        return {'FINISHED'}

class OBJECT_OT_export_spaces_mp4to5(bpy.types.Operator, ExportHelper):
    """Export spaces to a bin file for mario party 4 - 5."""
    bl_idname = "object.export_spaces"
    bl_label = "Export Spaces"    
    bl_options   = {'PRESET', 'UNDO'}

    filename_ext = ".bin"
    filter_glob: StringProperty(
        default="*.bin;",
        options={'HIDDEN'},
    )
    def execute(self, context):
        isVersion2 = False
        spaces = space_file.convert_from_blender(context)
        space_file.write(spaces, self.filepath, isVersion2)
        return {'FINISHED'}

class OBJECT_OT_export_spaces_mp6to8(bpy.types.Operator, ExportHelper):
    """Export spaces to a bin file for mario party 6 - 8."""
    bl_idname = "object.export_spaces68"
    bl_label = "Export Spaces"    
    bl_options   = {'PRESET', 'UNDO'}

    filename_ext = ".bin"
    filter_glob: StringProperty(
        default="*.bin;",
        options={'HIDDEN'},
    )
    def execute(self, context):
        isVersion2 = True
        spaces = space_file.convert_from_blender(context)
        space_file.write(spaces, self.filepath, isVersion2)
        return {'FINISHED'}


class OBJECT_OT_add_party_path(bpy.types.Operator):
    """Add a new party path (poly‑curve)"""
    bl_idname = "object.add_party_path"
    bl_label = "Party Path"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Use mesh vertices so we can add custom attributes
        # Blender paths lack per point properties and is seemingly impossible to do so.
        mesh_data = bpy.data.meshes.new(name="PartyPath")

        verts = [
            (0.0, 0.0, 0.0),
            (1000.0, 0.0, 0.0),
            (1000.0, 1000.0, 0.0),
        ]
        edges = [(0, 1), (1, 2)]

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

        scale_attr = mesh_data.attributes["Scale"]
        for i in range(len(verts)):
            scale_attr.data[i].vector = (1, 1, 1)

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
        return {'FINISHED'}