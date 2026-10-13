# Blender GCN Mario Party Plugin
 
 A WIP board editor which can create custom board spaces and import/export HSF models all within blender.
 This is mainly aimed at Mario Party 4, with more games planned.

 Rigs are not supported due to issues with blender bones always breaking animations on reimport. 
 Bones will import as nodes instead which keep full SRT data intact.

## The tool features:
- HSF model import/exporting
- HSF material previewing with custom blender render. This is roughly accurate but very much a WIP.
- Board space editor with custom renderer. Create with Curve - Party Path object.
- Supports multiple space paths. Can be used to add multiple space layers.
- Should support blender 5.0+ and work as low as blender 3.3. 

It is very highly recommended you use custom board code when creating a board as replacing existing is difficult and hardcodeds various things.
Mario Party 4 has a full decompilation project which makes this easy and mario party 5 is partial which can already load custom rels.

# Credits
- [mariopartyrd](https://github.com/mariopartyrd)
	Huge thanks to mariopartyrd for the decomp effort improving hsf and board support along with making custom code possible.
	Also for the lzss.c code used for compression.
- [berrybush](https://github.com/hayden0729/berrybush) [license](https://github.com/hayden0729/berrybush?tab=GPL-3.0-1-ov-file)
	GX functions for texture decoding and tri-strips.
- [Rainchus](https://github.com/Rainchus)
	For dolphin_rels_to_mod.py script. Not used at this time but useful for testing board rels.
	
# Known issues/todo
- Bones are imported as nodes and armature exporting is not supported yet. 
I have not found a good method to import/export bones while retaining euler values as it causes existing animations to break! Feel free to make a PR for a fix.
- Rendering HSF is a WIP and may not display certain things accurately.
- Board UI only supports MP4-MP6 and can be set in blender/UI.json. Need documentation for MP7 and MP8.
- Need to add board specific flag UI where users can customize and configure their own event flags.

