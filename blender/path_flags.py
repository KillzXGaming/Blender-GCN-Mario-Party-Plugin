import bpy
import math
import ctypes
import json
from bpy.props import *
from . import game_config

class DynamicCategoryPanel(bpy.types.Panel):
    """Tool panel for editing path point flags."""
    bl_label = "Party Path Flags"
    bl_idname = "OBJECT_PT_party_path_flags"
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
        props = mesh.party_properties

        game_json = game_config.get_game(props.get_active_index())
        if game_json is None:
            return

        row = layout.row(align=True)
        row.label(text="Raw Flags")
        row.prop(mesh.party_properties, "Flags", text="")

        # MP6 and later keep 16 more bits in FlagsExtra
        if any(f.get("field") == "flags_ex" for f in game_json["flags"]):
            row = layout.row(align=True)
            row.label(text="Raw Flags Ex")
            row.prop(mesh.party_properties, "FlagsExtra", text="")

        i = 0
        row = layout.row(align=True)
        for i in range(16):
            row.label(text=str(i))

        layout.prop(mesh.party_properties, "flagBits1", text="")
        layout.prop(mesh.party_properties, "flagBits2", text="")

        scene_props = getattr(context.scene, "party_properties", None)
        board_id = scene_props.boad_id if scene_props else ""
        type_id = props.SpaceTypeId

        for flag_json in game_json["flags"]:
            prop_id = flag_json["_prop_id"]
            if not hasattr(props, prop_id):
                continue
            # space types and boards can show certain flags
            if not game_config.flag_visible(flag_json, type_id, board_id):
                continue
            layout.prop(props, prop_id)

"""Generates a property for editing flag bit data."""
def make_prop(name, item, enum_list):
    prop_id = name
    def update_flags(self, ctx):
        if not hasattr(ctx, "object"):
            return
        update_flag_property(ctx, item)

    common = dict(
        name=item.get("label", "id"),
        description=item.get("description", ""),
        update=update_flags,
    )
    t = item["type"]
    if t == "float":
        return FloatProperty(
            **common,
            min=item.get("min", -999999.0),
            max=item.get("max", 999999.0),
            default=item.get("default", 0.0))
    if t == "int":
        return IntProperty(
            **common,
            min=item.get("min", -999999),
            max=item.get("max", 999999),
            default=item.get("default", 0))
    if t == "bool":
        return BoolProperty(
            **common,
            default=item.get("default", False))
    if t == "enum":
        items = []

        json_items = []
        if item.get("enum_list", None) != None:
            for v in (enum_list or []):
                if v["id"] == item["enum_list"]:
                    json_items = v["items"]
        else:
            json_items = item["items"]

        for entry in json_items:
            if ":" in entry:
                label, value = entry.split(":", 1)
                identifier = value.strip() # value
                name = label.strip()       # display name
            else:
                identifier = entry
                name = entry
            items.append((identifier, name, ""))
        return EnumProperty(
            **common,
            items=items,
            default=items[0][0])

    print("Unknown property type:", t)
    return None

def get_property_id(item_name):
    return item_name.replace(" ", "_").lower()

def get_bits_i32(value: int, offset: int, width: int) -> int:
    value = i32_to_u32(value)
    mask = (1 << width) - 1
    return (value >> offset) & mask

def get_bits(value: int, offset: int, width: int) -> int:
    mask = (1 << width) - 1
    return (value >> offset) & mask

def set_bits(value: int, offset: int, width: int, new: int) -> int:
    mask = (1 << width) - 1
    if new & ~mask:
        raise ValueError(f"{new} does not fit in {width} bits")
    cleared = value & ~(mask << offset)
    return cleared | ((new & mask) << offset)

def clear_bit_range(val: int, start: int, end: int) -> int:
    if not (0 <= start <= end):
        raise ValueError("start must be <= end and both non‑negative")
    width = end - start + 1
    range_mask = ((1 << width) - 1) << start
    return val & ~range_mask

def flag_field(json_item) -> str:
    """Which stored value a flag edits: "flags" (default, 32 bits) or "flags_ex" (16 bits)."""
    return "flags_ex" if json_item.get("field", "flags") == "flags_ex" else "flags"

def read_field(props, json_item) -> int:
    if flag_field(json_item) == "flags_ex":
        return props.FlagsExtra & 0xFFFF
    return i32_to_u32(props.Flags)

def write_field(props, json_item, value: int):
    if flag_field(json_item) == "flags_ex":
        props.FlagsExtra = ctypes.c_int16(value & 0xFFFF).value
    else:
        props.Flags = u32_to_i32(value)

def u32_to_i32(mask: int) -> int:
    return ctypes.c_int32(mask).value

def i32_to_u32(mask: int) -> int:
    return ctypes.c_uint32(mask).value

def update_flag_property(ctx, json_item):
    obj = ctx.object
    if obj is None:
        return
    mesh = obj.data
    props = mesh.party_properties
    if props.updating_flags:
        return

    prop_id = json_item["_prop_id"]
    if not hasattr(props, prop_id):
        return

    prop_value = props.get_value(prop_id)
    input_flags = read_field(props, json_item)
    # Set flags
    bit_start = json_item.get("start", 0)
    bit_count = json_item.get("count", 0)
    bit_clear = json_item.get("clear_bits", 0)
    bit_value = 0
        
    # Bit ranges to clear as start:count, ie "7:2" or "19:2,25:5"
    if bit_clear and ":" in bit_clear:
        for clear_range in bit_clear.split(","):
            start_str, count_str = clear_range.split(":", 1)
            clear_start = int(start_str.strip())
            clear_count = int(count_str.strip())
            input_flags = clear_bit_range(input_flags, clear_start, clear_start + clear_count - 1)

    if json_item["type"] == "enum":
        if ":" in prop_value: # bit range
            start_str, count_str = prop_value.split(":", 1)
            bit_start = int(start_str.strip())
            bit_count = int(count_str.strip())
        else: # single bit edit
            bit_start = int(prop_value)
            # 0 is the "none" entry, only the clear range applies
            bit_count = 1 if bit_start != 0 else 0
            bit_value = 1 if bit_start != 0 else 0

    elif json_item["type"] == "int":
        bit_value = int(prop_value)
    elif json_item["type"] == "bool":
        bit_value = bool(prop_value)
    elif json_item["type"] == "float":
        bit_value = float(prop_value)

    print(f"update_flag_property {bit_start} {bit_count} {bit_value}")

    if bit_count:
        input_flags = set_bits(input_flags, bit_start, bit_count, bit_value)

    props.updating_flag_props = True
    try:
        write_field(props, json_item, input_flags)
    finally:
        props.updating_flag_props = False

def set_flag_property(json_item, props):
    prop_id = json_item["_prop_id"]
    if not hasattr(props, prop_id):
        return

    # Set flags
    bit_start = json_item.get("start", 0)
    bit_count = json_item.get("count", 0)
    bit_clear = json_item.get("clear_bits", 0)
    bit_value = 0

    prop_value = None
    if json_item["type"] == "enum":
        prop_enum = props.bl_rna.properties[prop_id]
        enum_items = [item.identifier for item in prop_enum.enum_items]
        prop_value = "0"
        for bit_item in enum_items:
            if ":" in bit_item: # bit range
                start_str, count_str = bit_item.split(":", 1)
                bit_start = int(start_str.strip())
                bit_count = int(count_str.strip())
            else: # single bit edit
                bit_start = int(bit_item)
                if bit_start != 0:
                    bit_count = 1

            val = get_bits(read_field(props, json_item), bit_start, bit_count)
            if val:
                prop_value = bit_item

    elif json_item["type"] == "int":
        prop_value = int(get_bits(read_field(props, json_item), bit_start, bit_count))
    elif json_item["type"] == "bool":
        prop_value = bool(get_bits(read_field(props, json_item), bit_start, bit_count))
    elif json_item["type"] == "float":
        prop_value = float(get_bits(read_field(props, json_item), bit_start, bit_count))

  #  print(f"set_flag_property {prop_id} {prop_value}")

    if prop_value != None:
        setattr(props, prop_id, prop_value)
