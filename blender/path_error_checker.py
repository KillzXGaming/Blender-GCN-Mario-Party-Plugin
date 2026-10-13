import bpy
import math
import ctypes
import json
from bpy.props import *
from . import space_file
from . import path_flags

def check_errors(context, operator, path_obj):
    # Get the space data
    space_list = space_file.convert_from_blender(context, self.path_obj)
    # Attempt to traverse the spaces like a player/com
    start_space = None
    for space in space_list:
        # Get starting space
        if space.Flags == -2147483648:
            start_space = space
        
    if start_space == None:
        operator.report({'ERROR'}, f"Failed to find a starting space! Make sure a \"Place\" property is set to Start Space. ")
        return

    traverse_spaces(space, space_list)

def traverse_spaces(space, space_list, enter_type = 0):
    # Player entering a shop, lottery, or boo house
    if is_place(space):
        # From here, we expect and need a player spot
        player_spot = False
        for idx in space.links:
            if is_player_enter(space_list[idx]):
                player_spot = space_list[idx]
        if not player_spot:
            operator.report({'ERROR'}, f"A shop/lottery/boo is missing a player enter space!")
            return
        if len(player_spot.links) == 0:
            operator.report({'ERROR'}, f"A player enter spot needs one connection for placing the shop/lottery/boo model.")
            return
    else:
        for idx in space.links:
            traverse_spaces(space_list[idx], space, enter_type)

def has_star_host(space, space_list):
    for idx in space.links:
        if is_star_host(space_list[idx])
            return True
    return False

def is_player_enter(space):
    if path_flags.get_bits(space.flags, 25, 1):
        return True
    return False

def is_star_host(space):
    if path_flags.get_bits(space.flags, 26, 1):
        return True
    return False

def is_place(space):
    # Shop
    if path_flags.get_bits(space.flags, 19, 1):
        return True
    # Shop 2
    if path_flags.get_bits(space.flags, 20, 1):
        return True
    # Boo
    if path_flags.get_bits(space.flags, 27, 1):
        return True
    # Lottery
    if path_flags.get_bits(space.flags, 28, 1):
        return True
    return False

