"""
Game specific configuration loaded from UI.json.
"""
import json
import os
import re

DEFAULT_SPRITE = 23

_games = None
_space_type_enum_cache = {}
_game_enum_cache = None

def json_path():
    return os.path.join(os.path.dirname(__file__), "UI.json")


def flag_prop_id(game_index, flag_id):
    """Returns a property name id"""
    fid = re.sub(r"\W", "_", str(flag_id)).lower()
    return f"g{game_index}_{fid}"


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _setup_space_types(game_index, raw_types):
    space_types = []
    seen = set()
    for entry in raw_types:
        type_id = _to_int(entry.get("type"))
        if type_id is None:
            print(f"UI.json game {game_index}: space type {entry.get('name')!r} has no valid 'type' id, skipped")
            continue
        if type_id in seen:
            print(f"UI.json game {game_index}: duplicate space type id {type_id}, skipped")
            continue
        seen.add(type_id)
        space_types.append({
            "name": str(entry.get("name", f"Type {type_id}")),
            "type": type_id,
            "sprite_index": _to_int(entry.get("sprite_index"), DEFAULT_SPRITE),
            "desc": str(entry.get("desc", "")),
        })
    return space_types


def _setup_flag(game_index, flag):
    flag["_prop_id"] = flag_prop_id(game_index, flag["id"])
    types = flag.get("on_types", flag.get("display_on_types"))
    flag["_on_types"] = None if types is None else {int(t) for t in types}
    return flag


def _setup_game(index, raw):
    game = dict(raw)
    game["index"] = index
    game["name"] = str(raw.get("name", f"Game {index}"))
    game["space_types"] = _setup_space_types(index, raw.get("space_types", []))
    game["space_type_lookup"] = {t["type"]: t for t in game["space_types"]}
    game["sprite_overrides"] = list(raw.get("sprite_overrides", []))
    game["enums"] = raw.get("enums") or []
    game["flags"] = [_setup_flag(index, f) for f in raw.get("flags", [])]
    return game


def load(force=False):
    """Returns the list of games."""
    global _games, _game_enum_cache
    if _games is not None and not force:
        return _games

    with open(json_path(), "r", encoding="utf-8-sig") as f:
        raw_games = json.load(f)

    _games = [_setup_game(i, g) for i, g in enumerate(raw_games)]
    _space_type_enum_cache.clear()
    _game_enum_cache = None
    return _games


def clamp_game_index(index):
    count = len(load())
    if count == 0:
        return 0
    return min(max(int(index), 0), count - 1)


def get_game(index):
    games = load()
    if not games:
        return None
    return games[clamp_game_index(index)]


def game_enum_items():
    global _game_enum_cache
    if _game_enum_cache is None:
        items = [(g["name"], g["name"], f"Game \"{g['name']}\"", "OBJECT_DATA", i)
                 for i, g in enumerate(load())]
        if not items:
            items = [("NONE", "None", "No games found in UI.json", "ERROR", 0)]
        _game_enum_cache = items
    return _game_enum_cache


def space_type_enum_items(game_index, current_type_id=None):
    """
    Enum items for the space type dropdown set per game.
    """
    game = get_game(game_index)
    types = game["space_types"] if game else []
    known = game["space_type_lookup"] if game else {}
    unknown = current_type_id is not None and current_type_id not in known

    key = (game["index"] if game else -1, current_type_id if unknown else None)
    items = _space_type_enum_cache.get(key)
    if items is None:
        items = [(str(t["type"]), t["name"], t["desc"], "", t["type"]) for t in types]
        if unknown:
            items.append((str(current_type_id), f"Unknown ({current_type_id})",
                          "This type id is not defined for the game in UI.json", "ERROR", current_type_id))
        if not items:
            items = [("0", "Type 0", "No space types are defined for this game in UI.json", "", 0)]
        _space_type_enum_cache[key] = items
    return items


def _override_matches(rule, flags):
    u_flags = flags & 0xFFFFFFFF
    if "flag_bit" in rule:
        return bool((u_flags >> int(rule["flag_bit"])) & 1)
    if "flags" in rule:
        return u_flags == (int(rule["flags"]) & 0xFFFFFFFF)
    return False


def get_sprite_index(game_index, type_id, flags):
    """Sprite sheet index for a point based on space type or sprite overrides."""
    game = get_game(game_index)
    if game is None:
        return DEFAULT_SPRITE

    for rule in game["sprite_overrides"]:
        if _override_matches(rule, flags):
            return int(rule["sprite_index"])

    space_type = game["space_type_lookup"].get(type_id)
    if space_type:
        return space_type["sprite_index"]
    return DEFAULT_SPRITE


def flag_visible(flag, type_id, board_id=""):
    """Determines if the flag property is visible."""
    types = flag.get("_on_types")
    if types is not None and type_id not in types:
        return False
    board = flag.get("on_board")
    if board:
        boards = board if isinstance(board, (list, tuple)) else [board]
        if str(board_id).lower() not in [str(b).lower() for b in boards]:
            return False
    return True
