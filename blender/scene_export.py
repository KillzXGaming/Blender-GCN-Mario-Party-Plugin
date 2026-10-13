import bpy, gpu
import subprocess
import sys
from pathlib import Path
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
import math
import bmesh
from . import space_file
import os
from . import blender_import
from . import blender_export
from ..hsf import hsf_file
from ..hsf import bin_mp
from .. import dolphin_rels_to_mod
from . import path_object

class FileItem(bpy.types.PropertyGroup):
    file_type_items = [
        ("MODELS", "Model", "", "", 0),
        ("SPACES", "Spaces", "", "", 1),
        ("SPRITES", "Sprites", "", "", 2),
        ("FILE", "Raw File", "", "", 3),
    ]

    @staticmethod
    def _model_collection_enum_items(context):
        items = []
        for i, col in enumerate(bpy.data.collections):
            items.append((col.name, col.name, f"Collection \"{col.name}\"", "OBJECT_DATA", i))
        if not items:
            items.append(("NONE", "None", "No collections in the scene!", "ERROR", 0))
        return items

    @staticmethod
    def _path_enum_items(context):
        objs = context.scene.objects
        items = []
        for i, obj in enumerate(sorted(objs, key=lambda o: o.name)):
            if obj.get("branch_path_draw", False):
                items.append((obj.name, obj.name, f"Space Path \"{obj.name}\"", "OBJECT_DATA", i))
        if not items:
            items.append(("NONE", "None", "No space path objects in the scene!", "ERROR", 0))
        return items


    def _set_collection_pointer_from_name(self, context):
        name = self.collect_name
        obj = bpy.data.collections.get(name)
        self.collect_obj = obj

    def _set_path_pointer_from_name(self, context):
        name = self.path_name
        obj = context.scene.objects.get(name)
        self.path_obj = obj

    file_name: bpy.props.StringProperty(default="")
    file_type : bpy.props.EnumProperty(name="Type", items=file_type_items)

    # space obj selection
    path_obj: bpy.props.PointerProperty(name="Spaces Object", type=bpy.types.Object)
    path_name: bpy.props.EnumProperty(
        name="Spaces",
        description="Select path to use as spaces",
        items=lambda self, ctx: FileItem._path_enum_items(ctx),
        update=lambda self, ctx: self._set_path_pointer_from_name(ctx),
    )
    # model collection selection
    collect_obj: bpy.props.PointerProperty(name="Collection", type=bpy.types.Collection)
    collect_name: bpy.props.EnumProperty(
        name="Collection of Models",
        description="Select collection to make as an HSF file.",
        items=lambda self, ctx: FileItem._model_collection_enum_items(ctx),
        update=lambda self, ctx: self._set_collection_pointer_from_name(ctx),
    )

    def get_extension(self):
        if self.file_type == "MODELS":
            return "hsf"
        if self.file_type == "SPACES":
            return "masu"
        if self.file_type == "SPRITES":
            return "atb"
        return "bin"

    def export(self, context, folder):
        print(f"Exporting {self.file_name} to {folder}")

        if self.file_type == "MODELS" and self.collect_obj:
            hsf = blender_export.create_hsf(self.collect_obj)
            hsf.save(folder / f"{self.file_name}.{self.get_extension()}")
        elif self.file_type == "SPACES" and self.path_obj:
            spaces = space_file.convert_from_blender(context, self.path_obj)
            space_file.write(spaces, folder / f"{self.file_name}.{self.get_extension()}")
        else:
            print(f"Failed to export type {self.file_type }")

class PartyEditorProps(bpy.types.PropertyGroup):
    game_path: bpy.props.StringProperty(default="")
    dolphin_path: bpy.props.StringProperty(default="")
    build_log: bpy.props.StringProperty(default="")
    boad_id: bpy.props.StringProperty(default="w30")
    file_list: bpy.props.CollectionProperty(type=FileItem)
    selected_file_index: bpy.props.IntProperty(default=-1)
    game_list : bpy.props.CollectionProperty(
        type=path_object.GameSettings,
        name="Game List",
    )

class SCENE_UL_file_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        ob = data
        if item:
            layout.prop(item, "file_name", text="", emboss=False, icon_value=icon)
            layout.prop(item, "file_type", text="", emboss=False, icon_value=icon)
        else:
            layout.label(text="", translate=False, icon_value=icon)

            
class SCENE_OT_add_file(bpy.types.Operator):
    bl_idname = "scene.add_file"
    bl_label = "Add File"
    bl_description = "Adds a file to load as a bin asset"

    def execute(self, context):
        properties = context.scene.party_properties
        new = properties.file_list.add()
        new.file_name = f"File {len(properties.file_list)}"
        # make the new item the active one
        properties.selected_file_index = len(properties.file_list) - 1
        return {'FINISHED'}

class SCENE_OT_remove_file(bpy.types.Operator):
    bl_idname = "scene.remove_file"
    bl_label = "Remove File"
    bl_description = "Removes a file from bin"

    def execute(self, context):
        properties = context.scene.party_properties
        idx = properties.selected_file_index
        flist = properties.file_list

        if 0 <= idx < len(flist):
            flist.remove(idx)
            properties.selected_file_index = min(max(0, idx - 1), len(flist) - 1)
        return {'FINISHED'}

class SCENE_OT_open_map_folder(bpy.types.Operator):
    bl_idname = "scene.open_map_folder"
    bl_label = "Open Map Folder"

    def execute(self, context):
        scene = context.scene
        game_root = Path(scene.party_properties.game_path).expanduser()
        boad_id = scene.party_properties.boad_id

        board_folder = game_root / "mod_root" / "maps" / boad_id
        os.startfile(board_folder)

        return {'FINISHED'}

class SCENE_OT_save_files(bpy.types.Operator):
    bl_idname = "scene.save_files"
    bl_label = "Save Files"

    def execute(self, context):
        scene = context.scene
        game_root = Path(scene.party_properties.game_path).expanduser()
        boad_id = scene.party_properties.boad_id
        files = scene.party_properties.file_list

        board_folder = game_root / "mod_root" / "maps" / boad_id
        for f in files:
            f.export(context, board_folder)

        macro_id = boad_id.upper()
        # Make a header file with the macro file names and file indices
        with open(board_folder / "order.txt", "w") as wr:
            for idx, f in enumerate(files):
                wr.write(f"{f.file_name}.{f.get_extension()}={idx}\n")

        # Make a header file with the macro file names and file indices
        with open(board_folder / "files.h", "w") as wr:
            wr.write(f"#ifndef DATANUM_{macro_id}_H\n")
            wr.write(f"#define DATANUM_{macro_id}_H\n")
            wr.write(f"\n")
            wr.write(f"#include \"datadir_enum.h\"\n")
            wr.write(f"\n")
            wr.write("enum{\n")
            for idx, f in enumerate(files):
                wr.write(f"    {macro_id}_{f.file_name.upper()} = DATA_MAKE_NUM(DATADIR_{macro_id}, {idx}),\n")
            wr.write("};\n")

        self.report({'INFO'}, "Finished saving!")

        return {'FINISHED'}

class SCENE_OT_game_boot(bpy.types.Operator):
    bl_idname = "scene.game_boot"
    bl_label = "Boot Game"

    def execute(self, context):
        scene = context.scene
        exe_path = Path(scene.party_properties.dolphin_path).expanduser()
        game_root = Path(scene.party_properties.game_path).expanduser()
        dol_path = game_root / "mod_root" / "mod" / "sys" / "main.dol"

        if not dol_path.is_file():
            self.report({'ERROR'}, f"Dol not found: {dol_path}")
            return {'CANCELLED'}

        if not exe_path.is_file():
            self.report({'ERROR'}, f"Executable not found: {exe_path}")
            return {'CANCELLED'}

        cmd = [str(exe_path), str(dol_path)]

        try:
            subprocess.Popen(
                cmd,
                creationflags = subprocess.CREATE_NEW_CONSOLE
            ).poll()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to launch: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

class SCENE_OT_build_board(bpy.types.Operator):
    bl_idname = "scene.build_board"
    bl_label = "Build"

    def execute(self, context):
        scene = context.scene

        game_root = Path(scene.party_properties.game_path).expanduser()
        scene.party_properties.build_log = ""
        # Compile the bin data
        boad_id = scene.party_properties.boad_id
        board_folder = game_root / "mod_root" / "maps" / boad_id
        bin_save_path = game_root / "mod_root" / "mod" / "files" / "data" / f"{boad_id}.bin"

        print(f"board_folder {board_folder}")

        bin_file = bin_mp.BinFile()
        bin_file.load_folder(board_folder)
        if len(bin_file.files) == 0:
            self.report({'ERROR'}, f"Failed to save bin. No file data found!")
            return {'CANCELLED'}

        bin_file.save(bin_save_path)

        # Compile the game code
        result = subprocess.run(
            ["py", "-m", "ninja"],
            cwd=str(game_root),
            capture_output=True,
            text=True)

        print(result.stdout)
        print(result.stderr)
        print(result.returncode)

        scene.party_properties.build_log = str(result.stdout)

        if result.returncode == 0: # do final transfer
            dolphin_rels_to_mod.transfer_files(scene.party_properties.game_path)

        self.report({'INFO'}, "Finished building!")

        return {'FINISHED'}


class SCENE_OT_file_select(bpy.types.Operator):
    bl_idname = "scene.pick_file"
    bl_label = "File"

    target_prop: bpy.props.StringProperty(options={'HIDDEN'})

    filepath: bpy.props.StringProperty(
        name="File",
        description="Path to directory"
    )

    def invoke(self, context, event):
        scene = context.scene
        try:
            cur_path = getattr(scene.party_properties, self.target_prop)
            if cur_path:
                self.filepath = cur_path
        except AttributeError:
            pass
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        self.report({'INFO'}, f"File selected: {self.filepath}")

        scene = context.scene
        if scene:
            try:
                setattr(scene.party_properties, self.target_prop, self.filepath)
            except AttributeError:
                self.report({'ERROR'}, f"Property {self.target_prop} not found")
                return {'CANCELLED'}
        return {'FINISHED'}

class SCENE_OT_folder_select(bpy.types.Operator):
    bl_idname = "scene.pick_folder"
    bl_label = "Folder"

    target_prop: bpy.props.StringProperty(options={'HIDDEN'})

    directory: bpy.props.StringProperty(
        name="Folder",
        description="Path to directory",
        subtype='DIR_PATH'
    )

    def invoke(self, context, event):
        scene = context.scene
        try:
            cur_path = getattr(scene.party_properties, self.target_prop)
            if cur_path:
                self.directory = cur_path
        except AttributeError:
            pass
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        self.report({'INFO'}, f"Folder selected: {self.directory}")

        scene = context.scene
        if scene:
            try:
                setattr(scene.party_properties, self.target_prop, self.directory)
            except AttributeError:
                self.report({'ERROR'}, f"Property {self.target_prop} not found")
                return {'CANCELLED'}
        return {'FINISHED'}

    def cancel(self, context):
        self.report({'INFO'}, "Folder picker cancelled")
        return {'CANCELLED'}

class SCENE_PT_party_editor(bpy.types.Panel):
    """Tool panel for building and compiling the board data."""
    bl_label = "Party Editor"
    bl_idname = "SCENE_PT_party_editor"
    bl_space_type = 'PROPERTIES' 
    bl_region_type = 'WINDOW'
    bl_context      = "scene" 

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.party_properties

        layout.prop(props, "build_log")
        layout.prop(props, "boad_id", text="Board ID")


        row = layout.row()
        row.prop(props, "game_path", text="Game Decomp")
        row.operator(
            SCENE_OT_folder_select.bl_idname,
            text="",
            icon='FILE_FOLDER'
        ).target_prop = "game_path"

        row = layout.row()
        row.prop(props, "dolphin_path", text="Dolphin")
        row.operator(
            SCENE_OT_file_select.bl_idname,
            text="",
            icon='FILE'
        ).target_prop = "dolphin_path"

        layout.operator(SCENE_OT_game_boot.bl_idname)
        layout.operator(SCENE_OT_build_board.bl_idname)
        layout.operator(SCENE_OT_save_files.bl_idname)
        layout.operator(SCENE_OT_open_map_folder.bl_idname)

        row = layout.row()
        row.template_list("SCENE_UL_file_list", "", props,
            "file_list", props, "selected_file_index", rows=3)

        col = row.column(align=True)
        col.operator(SCENE_OT_add_file.bl_idname, icon='ADD', text="")
        col.operator(SCENE_OT_remove_file.bl_idname, icon='REMOVE', text="")

        file_idx = props.selected_file_index
        if 0 <= file_idx < len(props.file_list):
            file = props.file_list[file_idx]

            layout.prop(file, "file_type")
            if file.file_type == "SPACES":
                layout.prop(file, "path_name")
            if file.file_type == "MODELS":
                layout.prop(file, "collect_name")

       # layout.operator("object.export_spaces")
       # layout.operator("object.import_spaces")