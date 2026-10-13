from . io_util import *
import ctypes
from . gx_tex import get_data_size_with_mips, export_texture, import_texture, GcnTextureFormats
from enum import IntEnum
import io
from typing import List, Tuple, Any, Dict
from dataclasses import dataclass, asdict, is_dataclass
import json

HSF_MAGIC = "HSFV037\x00"

# Material or object flags
HSF_MATERIAL_BILLBOARD = (1 << 0)
HSF_MATERIAL_NOCULL =  (1 << 1) # Show both face sides
HSF_MATERIAL_SHADOW  = (1 << 2) # Display shadow
HSF_MATERIAL_SHADOWMAP =  (1 << 3) # Display shadow map
HSF_MATERIAL_BLEND_ADDCOL = (1 << 4) # Blend add
HSF_MATERIAL_BLEND_INVCOL = (1 << 5) # Blend inv
HSF_MATERIAL_HILITE = (1 << 8) # Add highlight map
HSF_MATERIAL_DISABLE_ZWRITE = (1 << 9) # Disable depth writing
HSF_MATERIAL_HIDE = (1 << 10) # Hides material, used by item hook meshes
HSF_MATERIAL_NEAR = (1 << 12)
HSF_MATERIAL_MATHOOK = (1 << 13) # Hook for direct custom tev 
HSF_MATERIAL_REFLECTMODEL = (1 << 14)

# Primitive flags
MATERIAL_INDEX_MASK = 0xFFF

# Attribute Defines
WRAP_CLAMP = 0
WRAP_REPEAT = 1
# Attribute Flags
ENABLE_NEAREST_FILTER = 0x40 # Use nearest filtering
ENABLE_MIPMAP = 0x80 # Use mipmaps
MIPMAP_BIT_POS = 7

class HSF_BLEND_MODE(IntEnum):
    SRCALPHA_ONE = 0
    ZERO_INVDSTCLR = 1
    SRCALPHA_INVSRCALPHA = 2

class HSF_VERTEX_MODE(IntEnum):
    FLAT = 0
    SHADING = 1
    SHADING_SPECULAR = 2
    SHADING_SPECULAR2 = 2
    VERTEX_ALPHA = 2
    VERTEX_COLOR_ALPHA = 2

class HSF_OBJECT_TYPE(IntEnum):
    NULL1 = 0
    REPLICA = 1
    MESH = 2
    ROOT = 3
    JOINT = 4
    EFFECT = 5
    CAMERA = 7
    LIGHT = 8
    MAP = 9

class HSF_PRIMITIVE_TYPE(IntEnum):
    TRIANGLE = 2
    QUAD = 3
    TRIANGLE_STRIP = 4

class HSF_CURVE_TYPE (IntEnum):
    STEP = 0
    LINEAR = 1
    BEZIER = 2
    BITMAP = 3
    CONSTANT = 4

class HSF_TRACK_TYPE(IntEnum):
    TRANSFORM = 2
    MORPH = 3 # Using the channel type as an index, sets the shape weights in obj mesh data
    CLUSTER = 5 # Always the base weight in HsfCluster
    CLUSTER_WEIGHT = 6 # channel indexes what weights to use from HsfCluster
    MATERIAL = 9
    ATTRIBUTE = 10

# type list based on the decomp motion code + values being default keyed/set
# some types are never set in the decomp motion code
class HSF_TRACK_CHANNEL(IntEnum):
    # Note, if the track type is a morph cluster/shape, 
    # the channel gets used as an index to the 32 morph weights
    # Material types
    AMBIENT_COLOR_R = 0
    AMBIENT_COLOR_G = 1
    AMBIENT_COLOR_B = 2
    MATERIAL_COLOR_R   = 49
    MATERIAL_COLOR_G   = 50
    MATERIAL_COLOR_B   = 51
    SHADOW_COLOR_R     = 52
    SHADOW_COLOR_G     = 53
    SHADOW_COLOR_B     = 54
    HILITE_SCALE       = 55
    MAT_UNKNOWN_2      = 56
    TRANSPARENCY       = 57
    MAT_UNKNOWN_3      = 58
    MAT_UNKNOWN_4      = 59
    REFLECTION_INTENSITY = 60
    MAT_UNKNOWN_5      = 61
    # Object types
    TRANSLATE_X = 8
    TRANSLATE_Y = 9
    TRANSLATE_Z = 10
    ROTATION_X = 28
    ROTATION_Y = 29
    ROTATION_Z = 30
    SCALE_X    = 31
    SCALE_Y    = 32
    SCALE_Z    = 33
    VISIBLE = 24 # toggles obj flag as 0x1000 when curve == 1.0
    OBJ_FLAG_25 = 25
    OBJ_FLAG_0x2000 = 26 # toggles obj flag as 0x2000 when curve == 1.0, disables culling when 0?
    OBJ_FLAG_27 = 27
    # 25 and 27 is another 1.0 type, but not set in the decomp
    # Attribute types
    # The transform TRS is from hsfdraw_struct_01 where the data is set at runtime
    ATTR_TRANSLATE_X = 8
    ATTR_TRANSLATE_Y = 9
    ATTR_TRANSLATE_Z = 10
    ATTR_ROTATION_X = 28
    ATTR_ROTATION_Y = 29
    ATTR_ROTATION_Z = 30
    ATTR_SCALE_X    = 31
    ATTR_SCALE_Y    = 32
    ATTR_SCALE_Z    = 33    

    ATTR_COMBINER_BLENDING  = 62
    ATTR_BUMP_INTENSITY = 63
    ATTR_TEXTURE_INTENSITY = 64
    ATTR_UNKNOWN5 = 65
    ATTR_UNKNOWN6 = 66
    ATTR_TEXTURE_INDEX = 67 
    # Light types (when obj type is 8)
    LIGHT_POS_X = 8
    LIGHT_POS_Y = 9
    LIGHT_POS_Z = 10
    LIGHT_AIM_X = 11
    LIGHT_AIM_Y = 12
    LIGHT_AIM_Z = 13
    # Camera types (when obj type is 7)
    CAMERA_POS_X = 8
    CAMERA_POS_Y = 9
    CAMERA_POS_Z = 10
    CAMERA_TARGET_X = 11
    CAMERA_TARGET_Y = 12
    CAMERA_TARGET_Z = 13
    CAMERA_ASPECT = 14
    CAMERA_FOV    = 15
    # Morph types (when track type == 2)
    BASE_MORPH  = 40 # Blends shape morphs
    # Not used in the decomp code but seem like duplicate keyed values of the obj transform
    # They may be keying both base and current transform in their tools
    B_TRANSLATE_X = 34
    B_TRANSLATE_Y = 35
    B_TRANSLATE_Z = 36
    B_ROTATION_X = 37
    B_ROTATION_Y = 38
    B_ROTATION_Z = 39
    B_SCALE_X    = 41
    B_SCALE_Y    = 42
    B_SCALE_Z    = 43

# Shared between obj and material
class HsfMatFlags:
    def __init__(self, value):
        self.flags = value
        # flag properties
        self.set_flag_properties()

    def set_flag_properties(self):
        self.has_billboard = self.flags & HSF_MATERIAL_BILLBOARD != 0
        self.show_all_faces = self.flags & HSF_MATERIAL_NOCULL != 0
        self.has_shadow = self.flags & HSF_MATERIAL_SHADOW != 0
        self.has_shadow_map = self.flags & HSF_MATERIAL_SHADOWMAP != 0
        self.has_lightmap = self.flags & HSF_MATERIAL_HILITE != 0
        self.depth_write = self.flags & HSF_MATERIAL_DISABLE_ZWRITE == 0
        self.is_visible = self.flags & HSF_MATERIAL_HIDE == 0
        self.alpha_test = self.flags & HSF_MATERIAL_NEAR != 0
        self.mat_hook = self.flags & HSF_MATERIAL_MATHOOK != 0
        self.reflect_model = self.flags & HSF_MATERIAL_REFLECTMODEL != 0

        # Flag based on hsfdraw SetBlendMode()
        if self.flags & HSF_MATERIAL_BLEND_ADDCOL or self.flags & HSF_MATERIAL_BLEND_INVCOL:
            if self.flags & HSF_MATERIAL_BLEND_ADDCOL:
                self.flag_blend_mode = HSF_BLEND_MODE.SRCALPHA_ONE
            else:
                self.flag_blend_mode = HSF_BLEND_MODE.ZERO_INVDSTCLR
        else:
            self.flag_blend_mode = HSF_BLEND_MODE.SRCALPHA_INVSRCALPHA

    def apply_flag_properties(self):
        self.toggle_flag(self.has_billboard, HSF_MATERIAL_BILLBOARD)
        self.toggle_flag(self.show_all_faces, HSF_MATERIAL_NOCULL)
        self.toggle_flag(self.has_shadow, HSF_MATERIAL_SHADOW)
        self.toggle_flag(self.has_shadow_map, HSF_MATERIAL_SHADOWMAP)
        self.toggle_flag(self.has_lightmap, HSF_MATERIAL_HILITE)
        self.toggle_flag(not self.depth_write, HSF_MATERIAL_DISABLE_ZWRITE)
        self.toggle_flag(not self.is_visible, HSF_MATERIAL_HIDE)
        self.toggle_flag(self.alpha_test, HSF_MATERIAL_NEAR)
        self.toggle_flag(self.mat_hook, HSF_MATERIAL_MATHOOK)
        self.toggle_flag(self.reflect_model, HSF_MATERIAL_REFLECTMODEL)

        # blend flags
        if self.flag_blend_mode == HSF_BLEND_MODE.SRCALPHA_ONE:
            self.toggle_flag(True, HSF_MATERIAL_BLEND_ADDCOL)
            self.toggle_flag(True, HSF_MATERIAL_BLEND_INVCOL)
        elif self.flag_blend_mode == HSF_BLEND_MODE.ZERO_INVDSTCLR:
            self.toggle_flag(True, HSF_MATERIAL_BLEND_ADDCOL)
            self.toggle_flag(False, HSF_MATERIAL_BLEND_INVCOL)
        else:
            self.toggle_flag(False, HSF_MATERIAL_BLEND_ADDCOL)
            self.toggle_flag(False, HSF_MATERIAL_BLEND_INVCOL)

    def toggle_flag(self, v:bool,  mask):
        if v:
            self.flags |= mask
        else:
            self.flags &= ~mask

class HsfShapeUnion(ctypes.Union):
    _fields_ = [
        ("count16", ctypes.c_uint16 * 2),
        ("vertexCnt", ctypes.c_uint32),
    ]

class HsfSection:
    def __init__(self):
        self.size:int = 0
        self.offset:int = 0

class HsfScene:
    def __init__(self):
        self.fogType:int = 0
        self.start:float = 0.0
        self.end:float = 0.0
        self.color:tuple = (0.298, 0.298, 0.298, 0)

class HsfEnvelope:
    """Envelopes which transform and blend cluster vertices with object matrix binds."""
    def __init__(self):
        self.name:str = ""
        self.singleBindOffset:int = 0
        self.doubleBindOffset:int = 0
        self.multiBindOffset:int = 0
        self.singleBindCount:int = 0
        self.doubleBindCount:int = 0
        self.multiBindCount:int = 0
        self.vertexCount:int = 0
        self.copyCount:int = 0

        self.singleBinds:List[HsfEnvelopeSingle] = []
        self.doubleBinds:List[HsfEnvelopeDouble] = []
        self.multiBinds:List[HsfEnvelopeMultiBind] = []

class HsfEnvelopeSingle:
    def __init__(self):
        self.boneIndex:int = 0
        self.positionIndex:int = 0
        self.positionCount:int = 0
        self.normalIndex:int = 0
        self.normalCount:int = 0

class HsfEnvelopeDouble:
    def __init__(self):
        self.bone1:int = 0
        self.bone2:int = 0
        self.count:int = 0
        self.weightOffset:int = 0
        self.weights:List[HsfEnvelopeDoubleWeight] = []

class HsfEnvelopeDoubleWeight:
    def __init__(self):
        self.weight:float = 0.0
        self.positionIndex:int = 0
        self.positionCount:int = 0
        self.normalIndex:int = 0
        self.normalCount:int = 0

class HsfEnvelopeMultiBind:
    def __init__(self):
        self.weightCount:int = 0
        self.positionIndex:int = 0
        self.positionCount:int = 0
        self.normalIndex:int = 0
        self.normalCount:int = 0
        self.weightOffset:int = 0
        self.weights:List[HsfEnvelopeMultiBindWeight] = []

class HsfEnvelopeMultiBindWeight:
    def __init__(self):
        self.boneIndex:int = 0
        self.weight:float = 0.0

class HsfMaterial:
    """Materials that determine how a hsf draw is rendered."""
    def __init__(self):
        self.name:str = ""
        self.unknown1:int = 0
        self.passFlag:int = 0
        self.vtxMode:int = HSF_VERTEX_MODE.SHADING
        self.ambientColorR:int = 128
        self.ambientColorG:int = 128
        self.ambientColorB:int = 128
        self.materialColorR:int = 255
        self.materialColorG:int = 255
        self.materialColorB:int = 255
        self.shadowColorR:int = 0
        self.shadowColorG:int = 0
        self.shadowColorB:int = 0
        self.hiliteScale:float = 50.0
        self.unknown2:float = 0.0
        self.invAlpha:float = 0.0
        self.unknown3:float = 0.0
        self.unknown4:float = 0.0
        self.reflectAlpha:float = 0.0
        self.unknown5:float = 0.0
        self.flag_props = HsfMatFlags(0)
        self.attributeCount:int = 0
        self.attributeSymbolIndex:int = 0

        self.attributeIndices:List[int] = []

    def get_key(self) -> int:
        data: Tuple = (
            self.name,
            self.unknown1,
            self.passFlag,
            self.vtxMode,
            self.ambientColorR,
            self.ambientColorG,
            self.ambientColorB,
            self.materialColorR,
            self.materialColorG,
            self.materialColorB,
            self.shadowColorR,
            self.shadowColorG,
            self.shadowColorB,
            self.hiliteScale,
            self.unknown2,
            self.invAlpha,
            self.unknown3,
            self.unknown4,
            self.reflectAlpha,
            self.unknown5,
            self.flag_props.flags,
            self.attributeCount,
            self.attributeSymbolIndex,
        )
        indices_part = tuple(self.attributeIndices)
        return hash((data, indices_part))

class HsfAttribute:
    """Attributes for handling texture maps."""
    def __init__(self):
        self.name:str = ""
        self.texAnimOffset:int = 0 # runtime pointer to draw data used for animations
        self.unknown1:int = 0
        self.blendingFlag:int = 0
        self.alphaFlag:int = 0
        self.blendTextureAlpha:float = 0.0
        self.unknown2:int  = 1
        self.nbtEnable:float = 0.0
        self.unknown3:int  = 0.0
        self.unknown4:int  = 0.0
        self.textureEnable:float  = 1.0 # Toggles texture off if not 1.0
        self.unknown5:float = 1.0
        # Static transform when no animations are used
        self.texAnimStart_Scale:tuple = (1.0, 1.0)
        self.texAnimStart_Translate:tuple = (0.0, 0.0)
        # Unused data
        self.texAnimEnd_Scale:tuple = (1.0, 1.0)
        # This could be unused init pos[3], rot[3], scale[3] data
        self.texAnimEnd_Translate:tuple = (0.0, 0.0)
        self.unknown6:float = 0.0
        self.texRotate:tuple = (0.0, 0.0, 0.0)
        self.unknown7:tuple = (1.0, 1.0, 1.0)
        self.wrapModeX:int = WRAP_CLAMP
        self.wrapModeY:int = WRAP_CLAMP
        self.unknown8:int = 1
        self.unknown9:int = 79
        self.unknown10:int = 0
        self.maxLOD:int = 0
        self.textureFlags:int = 0  #  & 0x80 = mipmap, 0x40 near filter, 0x100 hilte reflect
        self.textureIndex:int = 0
        self.use_nearest_filter = False
        self.use_mipmap_lod = False
        self.use_hilte_reflect = False

    def get_key(self) -> int:
        data = (
            self.name,
            self.texAnimOffset,
            self.unknown1,
            self.blendingFlag,
            self.alphaFlag,
            self.blendTextureAlpha,
            self.unknown2,
            self.nbtEnable,
            self.unknown3,
            self.unknown4,
            self.textureEnable,
            self.unknown5,
            self.texAnimStart_Scale,
            self.texAnimStart_Translate,
            self.texAnimEnd_Scale,
            self.texAnimEnd_Translate,
            self.unknown6,
            self.texRotate,
            self.unknown7,
            self.wrapModeX,
            self.wrapModeY,
            self.unknown8,
            self.unknown9,
            self.unknown10,
            self.maxLOD,
            self.textureFlags,
            self.textureIndex,
        )
        return hash(data)

    def set_flag_properties(self):
        self.use_nearest_filter = self.textureFlags & 0x40 != 0
        self.use_mipmap_lod = self.textureFlags & 0x80 != 0
        self.use_hilte_reflect = self.textureFlags & 0x100 != 0

    def apply_flag_properties(self):
        self.toggle_flag(self.use_nearest_filter, 0x40)
        self.toggle_flag(self.use_mipmap_lod, 0x80)
        self.toggle_flag(self.use_hilte_reflect, 0x100)

    def toggle_flag(self, v:bool,  mask):
        if v:
            self.textureFlags |= mask
        else:
            self.textureFlags &= ~mask

class HsfFace:
    """Face data for drawing mesh primitives."""
    def __init__(self):
        self.name:str = ""
        self.primitives:List[HsfFacePrimitive] = []

class HsfFacePrimitive:
    """Primitives that draw vertex groups"""
    def __init__(self):
        self.type: int = HSF_PRIMITIVE_TYPE.TRIANGLE
        self.flags: int = 32768
        self.vertex_groups: List[HsfVertexGroup] = []
        self.nbt: tuple = (0, 1, 0)

    def get_material_index(self):
        return self.flags & 0xFFF

    def set_material_index(self, index):
        self.flags &= ~0xFFF
        self.flags |= index

class HsfVertexGroup:
    def __init__(self):
        self.positionIndex:int = -1
        self.normalIndex:  int = -1
        self.colorIndex:   int = -1
        self.texCoordIndex:int = -1


class HsfBuffer:
    def __init__(self):
        self.name:   str = ""
        self.count:  int = 0
        self.offset: int = 0
        self.values: List[Any] = []

    def find_index(self, item) -> int:
        return self.values.index(item) 

class HsfObject:
    SIZE = 0x144

    def __init__(self):
        self.name :str= ""
        self.type:int = 0
        self.constant_offset:int = 0
        self.flag_props = HsfMatFlags(256)
        self.data:HsfObjectData = None
        self.index = 0

    def toggle_flag(self, v:bool,  mask):
        if v:
            self.flags |= mask
        else:
            self.flags &= ~mask

class HsfTransform :
    def __init__(self):
        self.pos:tuple = (0.0, 0.0, 0.0)
        self.rot:tuple = (0.0, 0.0, 0.0)
        self.sca:tuple = (1.0, 1.0, 1.0)
        
class HsfCamera :
    def __init__(self):
        self.pos:tuple = (0.0, 0.0, 0.0)
        self.target:tuple = (0.0, 0.0, 0.0)
        self.aspect_dupe:float = 1.0
        self.fov:float = 45.0
        self.near:float = 1.0
        self.far:float = 100000.0

class HsfLight :
    def __init__(self):
        self.pos:tuple = (0.0, 0.0, 0.0)
        self.target:tuple = (0.0, 0.0, 0.0)
        self.type:int = 0
        self.r:int = 255
        self.g:int = 255
        self.b:int = 255
        self.unk2C:float = 0.0
        self.ref_distance:float = 0.0
        self.ref_brightness:float = 0.0
        self.cutoff:float = 0.0

class HsfObjectData:

    def __init__(self):
        self.parentIndex:int = -1
        self.childrenCount:int = 0
        self.childrenSymbolIndex:int = -1
        self.baseTransform:HsfTransform = HsfTransform()
        self.currentTransform:HsfTransform = HsfTransform()
        self.currentTransform.sca = (0.0, 0.0, 0.0)
        self.replicaIndex = 0
        self.min:tuple = (0.0, 0.0, 0.0)
        self.max:tuple = (0.0, 0.0, 0.0)
        # Blends between 2 shapes when shapeType == 0. ie 4.3 blends shape 4 and 5.
        self.baseMorph:float = 0.0
        self.faceIndex:int = -1
        self.vertexIndex:int = -1
        self.normalIndex:int = -1
        self.colorIndex:int = -1
        self.texCoordIndex:int = -1
        self.materialDataOffset:int = 0
        self.attributeIndex:int = 0
        self.clusterUpdatedRuntimeFlag:int = 0 # determines when a cluster has been set
        self.unknown3:int = 150 # not used in the decomp code
        # shapeType = 2 determines to blend all shapes using morphWeights[] 
        # else it defaults to using base morph
        self.shapeType:int = 0
        self.hiliteAnimFlags:int = 48 # hiliteAnimIdx = (hiliteAnimFlags >> 4) & 0xF (when material flags == 0)
        self.shapeCount:int = 0
        self.shapeSymbolIndex:int = -1
        self.cluserCount:int = 0
        self.cluserSymbolIndex:int = -1
        self.envelopeIndex:int = -1
        self.envelopeCount:int = 0
        self.clusterPositionsOffset:int = 0
        self.clusterNormalsOffset:int = 0
        self.morphWeights:List[float] = [0.0] * 33

        # Indices for what shapes to morph (only used when obj type == 2)
        self.shapeIndices:List[int] = []
        # Indices for what cluster vertices to morph (only used when obj type == 2)
        self.clusterIndices:List[int] = []
        self.childrenIndices:List[int] = []

class HsfTexture:

    def __init__(self):
        self.name:str = ""
        self.max_lod:int = 0
        self.format:int = 7 # CMPR default
        self.bpp:int = 8
        self.width:int = 0
        self.height:int = 0
        self.palette_count:int = 0
        self.tint_color:int = 0
        self.palette_index:int = -1
        self.padd:int = 0
        self.data = []

    def get_rgba(self, hsf):
        gcnFormat = self.get_gcn_format()
        if self.palette_count > 0:
            palette_info = hsf.palettes[self.palette_index]
            return export_texture(self.width, 
                self.height, 
                self.data, 
                gcnFormat,
                self.get_gcn_palette_format(), palette_info.data)
        else:
            return export_texture(self.width, self.height, self.data, gcnFormat)

    def import_texture(self, hsf, rgba, w, h):

        gcnFormat = self.get_gcn_format()
        if self.format in (9, 10, 11): # force non palette type
            self.palette_count = 0
            self.palette_index = -1
            if self.format == 9:
                self.format = 4
            if self.format == 10:
                self.format = 5
            if self.format == 11:
                self.format = 3
            gcnFormat = self.get_gcn_format()

        self.max_lod = 0
        self.width, self.height, self.data = import_texture(rgba, w, h, gcnFormat)

    def get_gcn_palette_format(self):
        if self.format == 9:
            return GcnTextureFormats.RGB565
        if self.format == 10:
            return GcnTextureFormats.RGB5A3
        return GcnTextureFormats.I8

    def get_gcn_format(self):
        gcn_formats = {}
        gcn_formats[0] = GcnTextureFormats.I4
        gcn_formats[1] = GcnTextureFormats.I8
        gcn_formats[2] = GcnTextureFormats.IA4
        gcn_formats[3] = GcnTextureFormats.IA8
        gcn_formats[4] = GcnTextureFormats.RGB565
        gcn_formats[5] = GcnTextureFormats.RGB5A3
        gcn_formats[6] = GcnTextureFormats.RGBA32
        gcn_formats[7] = GcnTextureFormats.CMPR
        if self.bpp == 4:
            gcn_formats[9] = GcnTextureFormats.C4 # RGB565 palette
            gcn_formats[10] = GcnTextureFormats.C4 # RGB5A3 palette
            gcn_formats[11] = GcnTextureFormats.C4 # IA8 palette
        else:
            gcn_formats[9] = GcnTextureFormats.C8 # RGB565 palette
            gcn_formats[10] = GcnTextureFormats.C8 # RGB5A3 palette
            gcn_formats[11] = GcnTextureFormats.C8 # IA8 palette
        return gcn_formats[self.format]

class HsfPalette:
    def __init__(self):
        self.name:str = ""
        self.format:int = 0
        self.palette = []

class HsfMotion:
    def __init__(self):
        self.name:str = ""
        self.frame_count:int = 0.0
        self.tracks:List[HsfTrack] = []
        
class HsfTrack:
    def __init__(self):
        self.type:int = HSF_TRACK_TYPE.TRANSFORM
        # Start index set at runtime used for bezier curves
        self.start:int = 0
        # The target string, often the object name
        self.targetString:str = None
        # The index of the list to target, ie materials, attributes
        self.targetIndex:int = 0
        # Channel to set values
        self.channel:int = HSF_TRACK_CHANNEL.AMBIENT_COLOR_R
        # Interpolation/curve mode
        self.interpolation:int = HSF_CURVE_TYPE.BEZIER
        self.key_count:int = 0
        self.keyframe_offset:int = 0
        # Constant value when interpolation is set to CONSTANT
        self.constant:float = 0.0
        self.key_frames:List[HsfKeyFrame] = []

class HsfKeyFrame:
    def __init__(self):
        self.frame = 0.0
        self.value = 0.0
        self.slope_in = 0.0
        self.slope_out = 0.0

class HsfCluster:
    """
    A cluster which is used to morph vertices
    It can blend up to 32 vertex buffers (type 2) or 2 buffers using base morph (type 0/1)
    A HSFPart from partIdx will determine what vertex indices to set in the buffer.
    """
    def __init__(self):
        self.name1:str = ""
        self.name2:str = ""
         # the target object name
        self.target:str = ""
        # The index to HsfPart which contains vertex indices
        self.partIdx:int = 0
        # Base morph weight
        self.baseMorph:float = 0.0
        # 33 morph weights to blend for animations
        self.weights:List[float] = [0.0] * 32
        # runtime value for when the cluster object target is set by target name
        self.isAdjusted:bool = False 
        self.unknown:int = 0
        # type 2 blend clusters between all weights
        # else it blends between base morph
        self.type:int = 0
        self.bufferCount = 0
        self.bufferSymbolIdx = -1

        # Indices for what position HSFBuffer to use
        self.buffer:List[int] = []

class HsfPart:
    """
    A cluster part which determines what vertices to update in the currently drawn vertex data.
    """
    def __init__(self):
        self.name:str = ""
        self.data = []

class HsfShape:
    """
    A shape which is used to morph vertices
    It can blend up to 32 shapes (shape_type 2) or 2 buffers using base morph (shape_type 0/1) from HsfObjectData
    """
    def __init__(self):
        self.name:str = ""
        self.unknown:int = 0
        self.bufferCount:int = 0
        self.bufferSymbolIdx:int = -1

        self.buffer:List[int] = []

class HsfMapAttribute:
    """
    Skeleton data which is used to init cluster envelopes.
    """
    def __init__(self):
        self.minX:float = 0.0
        self.minY:float = 0.0
        self.minZ:float = 0.0
        self.data = []
        
class HsfSkeleton:
    """
    Skeleton data which is used to init cluster envelopes.
    """
    def __init__(self):
        self.name:str = ""
        self.transform = HsfTransform()

class HsfMatrixList:
    """
    Matrices which are set at runtime used to calculate cluster envelope matrices.
    """
    def __init__(self):
        self.meshMatrices:List[HsfMatrix] = []
        self.nodeMatrices:List[HsfMatrix] = []
        self.allMatrices:List[HsfMatrix] = []

class HsfMatrix:
    """
    A matrix used to store cluster envelope data.
    """
    def __init__(self):
        self.base_idx:int = 0
        self.count:int = 0
        self.data:tuple = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)

class HsfFile:

    def __init__(self):
        self.scene = HsfScene()
        self.symbols:List[int] = []
        self.vertices: List[HsfBuffer] = []
        self.normals: List[HsfBuffer] = []
        self.colors: List[HsfBuffer] = []
        self.tex_coords: List[HsfBuffer] = []
        self.faces: List[HsfFace] = []
        self.objects: List[HsfObject] = []
        self.textures: List[HsfTexture] = []
        self.palettes: List[HsfPalette] = []
        self.motions: List[HsfMotion] = []
        self.materials: List[HsfMaterial] = []
        self.attributes: List[HsfAttribute] = []
        self.map_attributes: List[HsfMapAttribute] = []
        self.matrices: List[HsfMatrixList] = []
        self.envelopes: List[HsfEnvelope] = []
        self.skeletons: List[HsfSkeleton] = []
        self.clusters: List[HsfCluster] = []
        self.parts: List[HsfPart] = []
        self.shapes: List[HsfShape] = []
        self.strings = []

    @classmethod
    def load(cls, filePath):
        with open(filePath, 'rb') as f:
            reader = BinaryReader(f, endian=">")
            instance = cls()
            instance.read(reader)
            return instance

    @classmethod
    def load_raw(cls, data: bytes):
        with io.BytesIO(data) as f:
            reader = BinaryReader(f, endian=">")
            instance = cls()
            instance.read(reader)
            return instance

    def get_symbol_indices(self, idx, count):
        if idx == -1 or count == 0:
            return []

        if len(self.symbols) < idx + count:
            raise ValueError(f"Invalid symbol range {idx}:{count} for symbol list {len(self.symbols)}. ")

        indices = []
        for i in range(count):
            indices.append(self.symbols[idx + i])
        return indices

    def save(self, filePath):
        with open(filePath, 'wb') as f:
            self.write(BinaryWriter(f, ">"))

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        writer = BinaryWriter(buf, endian=">")
        self.write(writer)
        return buf.getvalue()

    def read(self, r):
        # HSFV037
        r.read_signature(HSF_MAGIC)

        # Get strings and symbols
        r.seek(160)
        self.symbols = self.read_section(r, self.read_symbols)
        self.strings = self.read_section(r, self.read_strings)

        # Get objects first, we need to check what formats are required for normals
        r.seek(72)
        self.objects = self.read_section(r, self.read_objects)

        # When normals use envelopes, the normals are float[3] rather than snorm_8_8_8
        self.normal_formats = {}
        for obj in self.objects:
            if obj.type == HSF_OBJECT_TYPE.MESH:
                self.normal_formats[obj.data.normalIndex] = obj.data.envelopeCount > 0

        r.seek(8)
        self.scene = self.read_section(r, self.read_scene)
        self.colors = self.read_section(r, self.read_colors)
        self.materials = self.read_section(r, self.read_materials)
        self.attributes = self.read_section(r, self.read_attributes)
        self.vertices = self.read_section(r, self.read_vertices)
        self.normals = self.read_section(r, self.read_normals)
        self.tex_coords = self.read_section(r, self.read_tex_coords)
        self.faces = self.read_section(r, self.read_faces)
        r.seek(8, 1) # objects here which is already read, skip
        self.textures = self.read_section(r, self.read_textures)
        self.palettes = self.read_section(r, self.read_palettes)
        self.motions = self.read_section(r, self.read_motions)
        self.envelopes = self.read_section(r, self.read_envelopes)
        self.skeletons = self.read_section(r, self.read_skeletons)
        self.parts = self.read_section(r, self.read_parts)
        self.clusters = self.read_section(r, self.read_clusters)
        self.shapes = self.read_section(r, self.read_shapes)
        self.map_attributes = self.read_section(r, self.read_map_attributes)
        self.matrices = self.read_section(r, self.read_matrix_list)

        print(f"clusters {len(self.clusters)} self.parts {len(self.parts)}")

    def read_section(self, r, func_read):
        offset = r.read_u32()
        count = r.read_u32()

        print(f"{offset} {count}")

        origin = r.tell()

        if offset != 0 and count != 0:
            r.seek(offset)
            result = func_read(r, count)
            r.seek(origin)
            return result

        return []

    def read_scene(self, r, count):
         scene = HsfScene()
         scene.fogType = r.read_u32()
         scene.start = r.read_f32()
         scene.end = r.read_f32()
         scene.color = r.read_color8()
         return scene

    def read_stub(self, r, count):
        pass

    def read_symbols(self, r, count):
        return r.read_u32s(count)

    def read_strings(self, r, size):
        strings = {}
        data_start = r.tell()
        data_end = r.tell() + size

        while r.tell() < data_end:
            offset = r.tell() - data_start
            strings[offset] = r.read_cstring()
        return strings

    def read_vertices(self, r, count):
        components = self.read_buffer_components(r, count)
        start = r.tell()
        for i in range(count):
            r.seek(start + components[i].offset)
            for c in range(components[i].count):
                components[i].values.append(r.read_vec3())

        return components

    def read_normals(self, r, count):
        components = self.read_buffer_components(r, count)
        start = r.tell()
        for i in range(count):
            r.seek(start + components[i].offset)
            for c in range(components[i].count):
                if self.normal_formats[i]:
                    components[i].values.append(r.read_vec3())
                else:
                    components[i].values.append(r.read_8_8_8_snorm())

        return components

    def read_colors(self, r, count):
        components = self.read_buffer_components(r, count)
        start = r.tell()
        for i in range(count):
            r.seek(start + components[i].offset)
            for c in range(components[i].count):
                components[i].values.append(r.read_color8())

        return components

    def read_tex_coords(self, r, count):
        components = self.read_buffer_components(r, count)
        start = r.tell()
        for i in range(count):
            r.seek(start + components[i].offset)
            for c in range(components[i].count):
                components[i].values.append(r.read_vec2())

        return components

    def read_materials(self, r, count):
        materials = []
        for i in range(count):
            mat = HsfMaterial()
            materials.append(mat)

            mat.name = self.read_string_offset(r)
            mat.unknown1 = r.read_u32()
            mat.passFlag = r.read_u16()
            mat.vtxMode = r.read_u8()
            mat.ambientColorR = r.read_u8()
            mat.ambientColorG = r.read_u8()
            mat.ambientColorB = r.read_u8()
            mat.materialColorR = r.read_u8()
            mat.materialColorG = r.read_u8()
            mat.materialColorB = r.read_u8()
            mat.shadowColorR = r.read_u8()
            mat.shadowColorG = r.read_u8()
            mat.shadowColorB = r.read_u8()
            mat.hiliteScale = r.read_f32()
            mat.unknown2 = r.read_f32()
            mat.invAlpha = r.read_f32()
            mat.unknown3 = r.read_f32()
            mat.unknown4 = r.read_f32()
            mat.reflectAlpha = r.read_f32()
            mat.unknown5 = r.read_f32()
            mat.flag_props.flags = r.read_u32()
            mat.flag_props.set_flag_properties()
            attributeCount = r.read_u32()
            attributeSymbolIndex = r.read_u32()
            mat.attributeIndices = self.get_symbol_indices(attributeSymbolIndex, attributeCount)

        return materials

    def read_attributes(self, r, count):
        attributes = []
        for i in range(count):
            attr = HsfAttribute()
            attributes.append(attr)

            attr.name = self.read_string_offset(r)
            attr.texAnimOffset = r.read_u32()
            attr.unknown1 = r.read_u16()
            attr.blendingFlag = r.read_u8()
            attr.alphaFlag = r.read_u8()
            attr.blendTextureAlpha = r.read_f32()
            attr.unknown2 = r.read_i32()
            attr.nbtEnable = r.read_f32()
            attr.unknown3 = r.read_f32()
            attr.unknown4 = r.read_f32()
            attr.textureEnable = r.read_f32()
            attr.unknown5 = r.read_f32()
            attr.texAnimStart_Scale = r.read_vec2()
            attr.texAnimStart_Translate = r.read_vec2()
            attr.texAnimEnd_Scale = r.read_vec2()
            attr.texAnimEnd_Translate = r.read_vec2()
            attr.unknown6 = r.read_f32()
            attr.texRotate = r.read_vec3()
            attr.unknown7 = r.read_vec3()
            attr.wrapModeX = r.read_u32()
            attr.wrapModeY = r.read_u32()
            attr.unknown8 = r.read_u32()
            attr.unknown9 = r.read_u32()
            attr.unknown10 = r.read_u32()
            attr.maxLOD = r.read_u32()
            attr.textureFlags = r.read_i32()
            attr.textureIndex = r.read_i32()
            attr.set_flag_properties()

        return attributes

    def read_faces(self, r, count):
        components = self.read_buffer_components(r, count)
        face_start = r.tell()

        faces = []

        ex_offset = face_start
        for i in range(count):
            ex_offset += components[i].count * 48

        for i in range(count):
            face = HsfFace()
            faces.append(face)
            face.name = components[i].name

            r.seek(face_start + components[i].offset)
            for c in range(components[i].count):
                origin = r.tell()

                prim = HsfFacePrimitive()
                face.primitives.append(prim)

                prim.type = r.read_u16()
                prim.flags = r.read_u16()

                # Either indices[4][4] 
                # or indices[3][4] and count+strip data for tri strips
                primCount = 3
                if prim.type == HSF_PRIMITIVE_TYPE.TRIANGLE or prim.type == HSF_PRIMITIVE_TYPE.QUAD:
                    primCount = 4
                vertices = self.read_vertex_groups(r, primCount)
                # tri strips
                if prim.type == HSF_PRIMITIVE_TYPE.TRIANGLE_STRIP:
                    primCount = r.read_u32()
                    stripIndex = r.read_u32()

                    saved_pos = r.tell()

                    r.seek(ex_offset + stripIndex * 8)
                    strip_vertices = self.read_vertex_groups(r, primCount)

                    r.seek(saved_pos)

                    merged_len = len(vertices) + primCount + 1
                    merged: List[VertexGroup] = [None] * merged_len
                    merged[:len(vertices)] = vertices
                    if len(vertices) > 1:
                        merged[3] = vertices[1]
                    else:
                        raise ValueError("Triangle primitive strip without a second vertex!")

                    start = len(vertices) + 1
                    merged[start:start + len(strip_vertices)] = strip_vertices
                    vertices = merged

                prim.nbt = r.read_vec3()
                prim.vertex_groups = vertices
                r.seek(origin + 48)

        return faces

    def read_vertex_groups(self, r, count):
        vertex_groups = []
        for i in range(count):
            v = HsfVertexGroup()
            vertex_groups.append(v)

            v.positionIndex = r.read_i16()
            v.normalIndex = r.read_i16()
            v.colorIndex = r.read_i16()
            v.texCoordIndex = r.read_i16()

        return vertex_groups

    def read_buffer_components(self, r, count):
        buffers = []
        for i in range(count):
            buffer = HsfBuffer()
            buffers.append(buffer)

            buffer.name = self.read_string_offset(r)
            buffer.count = r.read_u32()
            buffer.offset = r.read_u32()
        return buffers

    def read_objects(self, r, count):
        objects = []
        for i in range(count):
            obj = HsfObject()
            objects.append(obj)

            obj.index = i
            origin = r.tell()

            obj.name = self.read_string_offset(r)
            obj.type = r.read_u32()
            obj.constant_offset = r.read_u32()
            obj.flag_props.flags = r.read_u32()
            obj.flag_props.set_flag_properties()

            if obj.type == HSF_OBJECT_TYPE.LIGHT:
                obj.data = self.read_light(r)
            elif obj.type == HSF_OBJECT_TYPE.CAMERA:
                obj.data = self.read_camera(r)
            else:
                obj.data = self.read_object_data(r, obj)

            r.seek(origin + HsfObject.SIZE)
        return objects

    def read_light(self, r):
        data = HsfLight()
        data.pos = r.read_vec3()
        data.target = r.read_vec3()
        data.type = r.read_u8()
        data.r = r.read_u8()
        data.g = r.read_u8()
        data.b = r.read_u8()
        data.unk2C = r.read_f32()
        data.ref_distance = r.read_f32()
        data.ref_brightness = r.read_f32()
        data.cutoff = r.read_f32()

        return data

    def read_camera(self, r):
        data = HsfCamera()
        data.pos = r.read_vec3()
        data.target = r.read_vec3()
        data.aspect_dupe = r.read_f32()
        data.fov = r.read_f32()
        data.near = r.read_f32()
        data.far = r.read_f32()
        return data

    def read_object_data(self, r, obj):
        data = HsfObjectData()
        data.parentIndex = r.read_i32()
        childrenCount = r.read_u32()
        childrenSymbolIndex = r.read_i32()
        data.baseTransform = self.read_transform(r)
        data.currentTransform = self.read_transform(r)
        if obj.type == HSF_OBJECT_TYPE.REPLICA:
            data.replicaIndex = r.read_i32()
            data.min = (0.0, r.read_f32(), r.read_f32())
        else:
            data.min = r.read_vec3()
        data.max = r.read_vec3()
        data.baseMorph = r.read_f32()
        data.morphWeights = r.read_f32s(33)
        data.faceIndex = r.read_i32()
        data.vertexIndex = r.read_i32()
        data.normalIndex = r.read_i32()
        data.colorIndex = r.read_i32()
        data.texCoordIndex = r.read_i32()
        data.materialDataOffset = r.read_u32()
        data.attributeIndex = r.read_i32()
        data.clusterUpdatedRuntimeFlag = r.read_u8()
        data.unknown3 = r.read_u8()
        data.shapeType = r.read_u8()
        data.hiliteAnimFlags = r.read_u8()
        shapeCount = r.read_u32()
        shapeSymbolIndex = r.read_i32()
        cluserCount = r.read_u32()
        cluserSymbolIndex = r.read_i32()
        data.envelopeCount = r.read_u32()
        data.envelopeIndex = r.read_i32() # Note, not a symbol index so no need to resolve
        data.clusterPositionsOffset = r.read_u32()
        data.clusterNormalsOffset = r.read_u32()

        # Todo some files pad random properties with 0xCCCCC
        if shapeSymbolIndex != -858993460:
            data.shapeIndices = self.get_symbol_indices(shapeSymbolIndex, shapeCount)
            data.clusterIndices = self.get_symbol_indices(cluserSymbolIndex, cluserCount)
            data.childrenIndices = self.get_symbol_indices(childrenSymbolIndex, childrenCount)

        return data

    def read_transform(self, r):
        transform = HsfTransform()
        transform.pos = r.read_vec3()
        transform.rot = r.read_vec3()
        transform.sca = r.read_vec3()
        return transform

    def read_textures(self, r, count):
        data_start = r.tell() + 32 * count

        textures = []
        for i in range(count):
            texture = HsfTexture()
            textures.append(texture)

            texture.name = self.read_string_offset(r)
            texture.max_lod = r.read_u32()
            texture.format = r.read_u8()
            texture.bpp = r.read_u8()
            texture.width = r.read_u16()
            texture.height = r.read_u16()
            texture.palette_count = r.read_u16()
            texture.tint_color = r.read_u32()
            texture.palette_index = r.read_i32()
            texture.padd = r.read_u32()

            data_offset = r.read_u32()

            origin = r.tell()
            r.seek(data_start + data_offset)
            texture.data = r.read_bytes(get_data_size_with_mips(
                texture.get_gcn_format(), 
                texture.width, 
                texture.height, 
                texture.max_lod))

            r.seek(origin)

        return textures

    def read_palettes(self, r, count):
        data_start = r.tell() + 16 * count

        palettes = []
        for i in range(count):
            palette = HsfPalette()
            palettes.append(palette)

            palette.name = self.read_string_offset(r)
            palette.format = r.read_u32()
            data_count = r.read_u32()
            data_offset = r.read_u32()

            origin = r.tell()
            r.seek(data_start + data_offset)
            palette.data = r.read_bytes(data_count * 2)

            r.seek(origin)

        return palettes

        
    def read_motions(self, r, count):
        motions = []
        track_data_start = r.tell() + 16 * count

        total_track_count = 0
        for i in range(count):
            motion = HsfMotion()
            motion.name = self.read_string_offset(r)
            track_count = r.read_u32()
            track_offset = r.read_u32()
            motion.frame_count = r.read_f32()

            total_track_count += track_count

            origin = r.tell()
            r.seek(track_data_start + track_offset)
            for t in range(track_count):
                track = HsfTrack()
                track.type = r.read_u8()
                track.start = r.read_u8()
                track.targetString = self.read_string_offset(r, True)
                track.targetIndex = r.read_i16()
                track.channel = r.read_u16()
                track.interpolation = r.read_u16()
                track.key_count = r.read_u16()
                if track.key_count > 0 and track.interpolation != 4:
                    track.keyframe_offset = r.read_u32()
                else:
                    track.constant = r.read_f32()

                motion.tracks.append(track)

            motions.append(motion)
            r.seek(origin)

        key_data_start = track_data_start + 16 * total_track_count

        for i in range(count):
            for t in range(track_count):
                track = motions[i].tracks[t]

                if track.key_count > 0 and track.interpolation != 4:
                    r.seek(key_data_start + track.keyframe_offset)
                    for t in range(track.key_count):
                        key_frame = HsfKeyFrame()
                        if track.interpolation == HSF_CURVE_TYPE.STEP:
                            key_frame.frame = r.read_f32()
                            key_frame.value = r.read_f32()
                        if track.interpolation == HSF_CURVE_TYPE.LINEAR: 
                            key_frame.frame = r.read_f32()
                            key_frame.value = r.read_f32()
                        if track.interpolation == HSF_CURVE_TYPE.BEZIER:
                            key_frame.frame = r.read_f32()
                            key_frame.value = r.read_f32()
                            key_frame.slope_in = r.read_f32()
                            key_frame.slope_out = r.read_f32()
                        if track.interpolation == HSF_CURVE_TYPE.BITMAP:
                            key_frame.frame = r.read_f32()
                            key_frame.value = r.read_u32()
                        track.key_frames.append(key_frame)

        return motions

    def read_envelopes(self, r, count):
        envelopes = []
        for i in range(count):
            env = HsfEnvelope()
            envelopes.append(env)

            env.name = self.read_string_offset(r)
            env.singleBindOffset = r.read_u32()
            env.doubleBindOffset = r.read_u32()
            env.multiBindOffset = r.read_u32()
            env.singleBindCount = r.read_u32()
            env.doubleBindCount = r.read_u32()
            env.multiBindCount = r.read_u32()
            env.vertexCount = r.read_u32()
            env.copyCount = r.read_u32()

        start = r.tell()

        for env in envelopes:
            if env.singleBindCount:
                r.seek(start + env.singleBindOffset)
                for i in range(env.singleBindCount):
                    singleBind = HsfEnvelopeSingle()
                    env.singleBinds.append(singleBind)

                    singleBind.boneIndex = r.read_u32()
                    singleBind.positionIndex = r.read_i16()
                    singleBind.positionCount = r.read_i16()
                    singleBind.normalIndex = r.read_i16()
                    singleBind.normalCount = r.read_i16()
            if env.doubleBindCount:
                r.seek(start + env.doubleBindOffset)
                for i in range(env.doubleBindCount):
                    doubleBind = HsfEnvelopeDouble()
                    env.doubleBinds.append(doubleBind)

                    doubleBind.bone1 = r.read_u32()
                    doubleBind.bone2 = r.read_u32()
                    doubleBind.weightCount = r.read_u32()
                    doubleBind.weightOffset = r.read_u32()
            if env.multiBindCount:
                r.seek(start + env.multiBindOffset)
                for i in range(env.multiBindCount):
                    multiBind = HsfEnvelopeMultiBind()
                    env.multiBinds.append(multiBind)

                    multiBind.weightCount = r.read_u32()
                    multiBind.positionIndex = r.read_i16()
                    multiBind.positionCount = r.read_i16()
                    multiBind.normalIndex = r.read_i16()
                    multiBind.normalCount = r.read_i16()
                    multiBind.weightOffset = r.read_u32()

        data_start = r.tell()
        for env in envelopes:
            for d in env.doubleBinds:
                r.seek(data_start + d.weightOffset)
                for i in range(d.weightCount):
                    dw = HsfEnvelopeDoubleWeight()
                    dw.weight = r.read_f32()
                    dw.positionIndex = r.read_i16()
                    dw.positionCount = r.read_i16()
                    dw.normalIndex = r.read_i16()
                    dw.normalCount = r.read_i16()
                    d.weights.append(dw)

            for m in env.multiBinds:
                r.seek(data_start + m.weightOffset)
                for i in range(m.weightCount):
                    mw = HsfEnvelopeMultiBindWeight()
                    mw.boneIndex = r.read_u32()
                    mw.weight = r.read_f32()
                    m.weights.append(mw)
        return envelopes

    def read_skeletons(self, r, count):
        skeletons = []
        for i in range(count):
            skel = HsfSkeleton()
            skel.name = self.read_string_offset(r)
            skel.transform = self.read_transform(r)
            skeletons.append(skel)

        return skeletons

    def read_parts(self, r, count):
        parts = []
        data_start = r.tell() + count * 12
        for i in range(count):
            part = HsfPart()
            parts.append(part)

            part.name = self.read_string_offset(r)
            num_data = r.read_u32()
            data_idx = r.read_u32()

            origin = r.tell()
            r.seek(data_start + data_idx * 2)
            part.data = r.read_u16s(num_data)

            r.seek(origin)

        return parts

    def read_clusters(self, r, count):
        clusters = []
        for i in range(count):
            cluster = HsfCluster()
            cluster.name1 = self.read_string_offset(r)
            cluster.name2 = self.read_string_offset(r)
            cluster.target = self.read_string_offset(r)
            cluster.partIdx = r.read_u32()
            cluster.baseMorph = r.read_f32()
            cluster.weights = r.read_f32s(32)
            cluster.isAdjusted = r.read_bool()
            cluster.unknown = r.read_u8()
            cluster.type = r.read_u16()
            bufferCount = r.read_u32()
            bufferSymbolIdx = r.read_u32()
            clusters.append(cluster)

            print(f"{cluster.name1 } {cluster.name2} {cluster.target }")

            cluster.buffer = self.get_symbol_indices(bufferSymbolIdx, bufferCount)

        return clusters

    def read_shapes(self, r, count):
        shapes = []
        for i in range(count):
            shape = HsfShape()
            shape.name = self.read_string_offset(r)
            # 2 counters
            # first one has
            # count16[2]
            shape.unknown = r.read_u16()
            bufferCount = r.read_u16()
            bufferSymbolIdx = r.read_u32()
            shapes.append(shape)

            shape.buffer = self.get_symbol_indices(bufferSymbolIdx, bufferCount)

        return shapes

    def read_map_attributes(self, r, count):
        map_attributes = []
        data_start = r.tell() + count * 24
        for i in range(count):
            map_attr = HsfMapAttribute()
            map_attr.minX = r.read_f32()
            map_attr.minY = r.read_f32()
            map_attr.minZ = r.read_f32()
            data_idx = r.read_u32()
            num_data = r.read_u16()

            origin = r.tell()
            r.seek(data_start + data_idx * 2)
            map_attr.data = r.read_u16s(num_data)

            r.seek(origin)

        return map_attributes

    def read_matrix_list(self, r, count):
        matrix_list = []
        for i in range(count):
            mat = HsfMatrixList()
            matrix_list.append(mat)

            num_meshes = r.read_u32()
            num_nodes = r.read_u32()
            r.read_u32() # 0

            mat.meshMatrices = self.read_matrices(r, num_meshes)
            mat.nodeMatrices = self.read_matrices(r, num_nodes)
            mat.allMatrices = self.read_matrices(r, num_meshes * num_nodes)
        return matrix_list

    def read_matrices(self, r, count):
        matrices = []
        for i in range(count):
            mat = HsfMatrix()
            matrices.append(mat)

            mat.base_idx = r.read_u32()
            mat.count = r.read_u32()
            mat.data = r.read_f32s(10)
        return matrices

    def read_string_offset(self, r, isShort = False):
        if isShort:
            offset = r.read_u16()
            if offset == 65535:
                return None
        else:
            offset = r.read_u32()
            if offset == 4294967295:
                return None

        return self.strings.get(offset, "")

    def write(self, wr):
        self._saved_strings = {}

        self.resolve_children_indices()
        self.resolve_symbols()

        self.normal_formats = {}
        for obj in self.objects:
            if obj.type == HSF_OBJECT_TYPE.MESH:
                self.normal_formats[obj.data.normalIndex] = obj.data.envelopeCount > 0

                print(f"{obj.name} normalIndex {obj.data.normalIndex}")

        wr.write_magic(HSF_MAGIC)
        # store and write the offsets/counters first
        scene_ofs        = self.write_section_header(wr, self.scene)
        colors_ofs       = self.write_section_header(wr, self.colors)
        materials_ofs    = self.write_section_header(wr, self.materials)
        attributes_ofs   = self.write_section_header(wr, self.attributes)
        vertices_ofs     = self.write_section_header(wr, self.vertices)
        normals_ofs      = self.write_section_header(wr, self.normals)
        tex_coords_ofs   = self.write_section_header(wr, self.tex_coords)
        faces_ofs        = self.write_section_header(wr, self.faces)
        objects_ofs      = self.write_section_header(wr, self.objects)
        textures_ofs     = self.write_section_header(wr, self.textures)
        palettes_ofs     = self.write_section_header(wr, self.palettes)
        motions_ofs      = self.write_section_header(wr, self.motions)
        envelopes_ofs    = self.write_section_header(wr, self.envelopes)
        skeletons_ofs    = self.write_section_header(wr, self.skeletons)
        parts_ofs        = self.write_section_header(wr, self.parts)
        clusters_ofs     = self.write_section_header(wr, self.clusters)
        shapes_ofs       = self.write_section_header(wr, self.shapes)
        map_attrs_ofs    = self.write_section_header(wr, self.map_attributes)
        matrices_ofs     = self.write_section_header(wr, self.matrices)
        symbols_ofs      = self.write_section_header(wr, self.symbols)
        strings_ofs      = self.write_section_header(wr, self._saved_strings)
        # write the sections in original order
        self.write_section(wr, scene_ofs,        self.scene,          self.write_scene)
        self.write_section(wr, materials_ofs,    self.materials,      self.write_materials)
        self.write_section(wr, attributes_ofs,   self.attributes,     self.write_attributes)

        self.write_section(wr, vertices_ofs,     self.vertices,       self.write_vertices)
        self.write_cluster_vertices(wr, self.vertices, False)

        self.write_section(wr, normals_ofs,      self.normals,        self.write_normals)
        self.write_cluster_vertices(wr, self.normals, True)

        self.write_section(wr, tex_coords_ofs,   self.tex_coords,     self.write_tex_coords)
        self.write_section(wr, objects_ofs,      self.objects,        self.write_objects)
        self.write_section(wr, colors_ofs,       self.colors,         self.write_colors)
        self.write_section(wr, faces_ofs,        self.faces,          self.write_faces)
        self.write_section(wr, textures_ofs,     self.textures,       self.write_textures)
        self.write_section(wr, palettes_ofs,     self.palettes,       self.write_palettes)
        self.write_section(wr, envelopes_ofs,    self.envelopes,      self.write_envelopes)
        self.write_section(wr, skeletons_ofs,    self.skeletons,      self.write_skeletons)
        self.write_section(wr, parts_ofs,        self.parts,          self.write_parts)
        self.write_section(wr, clusters_ofs,     self.clusters,       self.write_clusters)
        self.write_section(wr, shapes_ofs,       self.shapes,         self.write_shapes)
        self.write_section(wr, map_attrs_ofs,    self.map_attributes, self.write_map_attributes)
        self.write_section(wr, matrices_ofs,     self.matrices,       self.write_matrix_list, False)
        self.write_section(wr, motions_ofs,      self.motions,        self.write_motions)
        self.write_section(wr, symbols_ofs,      self.symbols,        self.write_symbols)

        # resolve string list

        # for string table, write full size
        str_start = wr.tell()

        self.write_target_offset(wr, strings_ofs, 0)
        for string, saved_ofs_list in self._saved_strings.items():
            # resolve each offset
            for ofs, is_short in saved_ofs_list:
                self.write_target_offset(wr, ofs, str_start, is_short)

            wr.write_cstring(string)

        str_end = wr.tell()

        # set string size
        wr.seek(172)
        wr.write_u32(str_end - str_start)

    def resolve_children_indices(self):
        for obj in self.objects:
            if hasattr(obj.data, "childrenIndices"):
                # make children indices set to empty
                obj.data.childrenIndices = []

        for i, obj in enumerate(self.objects):
            parent_idx = getattr(obj.data, "parentIndex", -1)
            if parent_idx < 0:
                continue
            if parent_idx >= len(self.objects):
                continue
            if parent_idx == i:
                continue

            parent_obj = self.objects[parent_idx]
            parent_obj.data.childrenIndices.append(i)

    def resolve_symbols(self):
        print(str(self.symbols))

        self.symbols = []
        for mat in self.materials:
            mat.attributeSymbolIndex = len(self.symbols)
            mat.attributeCount = len(mat.attributeIndices)
            for idx in mat.attributeIndices:
                self.symbols.append(idx)

        for obj in self.objects:
            if hasattr(obj.data, "childrenIndices"):
                obj.data.childrenSymbolIndex = len(self.symbols)
                obj.data.childrenCount = len(obj.data.childrenIndices)
                for idx in obj.data.childrenIndices:
                    self.symbols.append(idx)

            if hasattr(obj.data, "shapeIndices"):
                obj.data.shapeSymbolIndex = len(self.symbols)
                obj.data.shapeCount = len(obj.data.shapeIndices)
                for idx in obj.data.shapeIndices:
                    self.symbols.append(idx)

            if hasattr(obj.data, "clusterIndices"):
                obj.data.cluserSymbolIndex = len(self.symbols)
                obj.data.cluserCount = len(obj.data.clusterIndices)
                for idx in obj.data.clusterIndices:
                    self.symbols.append(idx)

        for cluster in self.clusters:
            cluster.bufferSymbolIdx = len(self.symbols)
            cluster.bufferCount = len(cluster.buffer)
            for idx in cluster.buffer:
                self.symbols.append(idx)

        for shape in self.shapes:
            shape.bufferSymbolIdx = len(self.symbols)
            shape.bufferCount = len(shape.buffer)
            for idx in shape.buffer:
                self.symbols.append(idx)

        print(str(self.symbols))

    def optimize_attributes(self):
        unique_attributes = {}
        new_attributes_list = []
        attributes_indices_remap = {}

        for i, attr in enumerate(self.attributes):
            attr.name = None

            attr_hash = attr.get_key()
            if attr_hash not in unique_attributes:
                new_idx = len(unique_attributes)

                attributes_indices_remap[i] = new_idx
                unique_attributes[attr_hash] = new_idx
                new_attributes_list.append(attr)
            else:
                attributes_indices_remap[i] = unique_attributes[attr_hash]

        self.attributes = new_attributes_list
        for mat in self.materials:
            for i, attrIdx in enumerate(mat.attributeIndices):
                mat.attributeIndices[i] = attributes_indices_remap[attrIdx]

        for motion in self.motions:
            for track in motion.tracks:
                if track.type == HSF_TRACK_TYPE.ATTRIBUTE:
                    attr_idx = track.targetIndex
                    track.targetIndex = attributes_indices_remap[attr_idx]

    def optimize_materials(self):
        unique_materials = {}
        new_material_list = []
        material_indices_remap = {}

        for i, mat in enumerate(self.materials):
            mat.name = "mat"

            mat_hash = mat.get_key()
            if mat_hash not in unique_materials:
                new_idx = len(unique_materials)

                material_indices_remap[i] = new_idx
                unique_materials[mat_hash] = new_idx
                new_material_list.append(mat)
            else:
                material_indices_remap[i] = unique_materials[mat_hash]

        self.materials = new_material_list

        for face in self.faces:
            for prim in face.primitives:
                mat_idx = prim.get_material_index()
                prim.set_material_index(material_indices_remap[mat_idx])

        for motion in self.motions:
            for track in motion.tracks:
                if track.type == HSF_TRACK_TYPE.MATERIAL:
                    mat_idx = track.targetIndex
                    track.targetIndex = material_indices_remap[mat_idx]

    def write_cluster_vertices(self, wr, vertices, isNormals):
        # for each obj with envelopes, store all vertices as cluser vertices
        for obj in self.objects:
            if obj.type == HSF_OBJECT_TYPE.MESH:
                data = obj.data

                if data.envelopeCount > 0:
                    wr.align(32)

                    if not isNormals:
                        data.clusterPositionsOffset = wr.tell()
                        values = vertices[data.vertexIndex].values
                    else:
                        data.clusterNormalsOffset = wr.tell()
                        values = vertices[data.normalIndex].values

                    for v in values:
                        wr.write_f32(v[0])
                        wr.write_f32(v[1])
                        wr.write_f32(v[2])

    def write_section_header(self, wr, section):
        origin = wr.tell()
        wr.write_u32(0) # offset for later

        if section is None:
            cnt = 0
        elif isinstance(section, list):
            cnt = len(section)
        else:
            cnt = 1

        wr.write_u32(cnt)
        return origin

    def write_section(self, wr, ofs, section, write_func, resolve_offset = False):
        # Some sections resolve the offset when empty, most leave it as 0
        # For 1 to 1 accuracy of the binary, do the same
        if not resolve_offset and (section is None or (isinstance(section, list) and len(section) == 0)):
            return

        self.write_target_offset(wr, ofs, 0)
        if section is None:
            return

        write_func(wr, section)

    def write_scene(self, wr, scene):
        wr.write_u32(scene.fogType)
        wr.write_f32(scene.start)
        wr.write_f32(scene.end)
        wr.write_color8(scene.color)

    def write_colors(self, wr, colors):
        self.write_buffers(wr, colors, wr.write_color8)

    def write_vertices(self, wr, vertices):
        self.write_buffers(wr, vertices, wr.write_vec3)

    def write_normals(self, wr, normals):
        self.write_buffers(wr, normals, wr.write_8_8_8_snorm, True)

    def write_tex_coords(self, wr, tex_coords):
        self.write_buffers(wr, tex_coords, wr.write_vec2)

    def write_buffers(self, wr, buffers: List[HsfBuffer], write_func, isNormals = False):
        start = wr.tell()
        for buf in buffers:
            self.write_string_offset(wr, buf.name)
            wr.write_u32(len(buf.values))
            wr.write_u32(0) # offset set after
        data_start = wr.tell()

        for i in range(len(buffers)):
            p = wr.tell()

            wr.align(32)

            self.write_target_offset(wr, start + i * 12 + 8, data_start)
            for v in buffers[i].values:
                # force float3 normals if necessary
                if isNormals and self.normal_formats[i]:
                    wr.write_vec3(v)
                else:
                    write_func(v)
        wr.align(4)


    def write_materials(self, wr, materials):
        for mat in materials:
            mat.flag_props.apply_flag_properties()

            self.write_string_offset(wr, mat.name)
            wr.write_u32(mat.unknown1)

            wr.write_u16(mat.passFlag)
            wr.write_u8(mat.vtxMode)

            wr.write_u8(mat.ambientColorR)
            wr.write_u8(mat.ambientColorG)
            wr.write_u8(mat.ambientColorB)

            wr.write_u8(mat.materialColorR)
            wr.write_u8(mat.materialColorG)
            wr.write_u8(mat.materialColorB)

            wr.write_u8(mat.shadowColorR)
            wr.write_u8(mat.shadowColorG)
            wr.write_u8(mat.shadowColorB)

            wr.write_f32(mat.hiliteScale)
            wr.write_f32(mat.unknown2)
            wr.write_f32(mat.invAlpha)
            wr.write_f32(mat.unknown3)
            wr.write_f32(mat.unknown4)
            wr.write_f32(mat.reflectAlpha)
            wr.write_f32(mat.unknown5)
            wr.write_u32(mat.flag_props.flags)
            wr.write_u32(mat.attributeCount)
            wr.write_u32(mat.attributeSymbolIndex)

    def write_attributes(self, wr, attributes):
        for attr in attributes:
            attr.apply_flag_properties()
            attr.name = None

            self.write_string_offset(wr, attr.name)
            wr.write_u32(attr.texAnimOffset)
            wr.write_u16(attr.unknown1)
            wr.write_u8(attr.blendingFlag)
            wr.write_u8(attr.alphaFlag)
            wr.write_f32(attr.blendTextureAlpha)
            wr.write_i32(attr.unknown2)
            wr.write_f32(attr.nbtEnable)
            wr.write_f32(attr.unknown3)
            wr.write_f32(attr.unknown4)
            wr.write_f32(attr.textureEnable)
            wr.write_f32(attr.unknown5)
            wr.write_vec2(attr.texAnimStart_Scale)
            wr.write_vec2(attr.texAnimStart_Translate)
            wr.write_vec2(attr.texAnimEnd_Scale)
            wr.write_vec2(attr.texAnimEnd_Translate)

            print(f"save {attr.texAnimStart_Scale}")

            wr.write_f32(attr.unknown6)
            wr.write_vec3(attr.texRotate)
            wr.write_vec3(attr.unknown7)
            wr.write_u32(attr.wrapModeX)
            wr.write_u32(attr.wrapModeY)
            wr.write_u32(attr.unknown8)
            wr.write_u32(attr.unknown9)
            wr.write_u32(attr.unknown10)
            wr.write_u32(attr.maxLOD)
            wr.write_i32(attr.textureFlags)
            wr.write_i32(attr.textureIndex)
        
    def write_vertex_groups(self, wr, vertex_groups):
        for v in vertex_groups:
            wr.write_i16(v.positionIndex)
            wr.write_i16(v.normalIndex)
            wr.write_i16(v.colorIndex)
            wr.write_i16(v.texCoordIndex)

    def write_faces(self, wr, faces):
        face_offset = 0
        # buffers
        for face in faces:
            self.write_string_offset(wr, face.name)
            wr.write_u32(len(face.primitives))
            wr.write_u32(face_offset)
            face_offset += len(face.primitives) * 48

        ex_offset = wr.tell()
        for face in faces:
            ex_offset += len(face.primitives) * 48

        tri_strips = []
        stripIndex = 0

        # primtives
        for face in faces:
            for prim in face.primitives:
                start = wr.tell()
                wr.write_u16(prim.type)
                wr.write_u16(prim.flags)

                if prim.type == HSF_PRIMITIVE_TYPE.TRIANGLE or prim.type == HSF_PRIMITIVE_TYPE.QUAD:
                    prim_count = 4
                else:
                    prim_count = 3
                    _strip_extra = prim.vertex_groups[4:] if len(prim.vertex_groups) > 4 else []

                self.write_vertex_groups(wr, prim.vertex_groups[:prim_count])
                if prim.type == HSF_PRIMITIVE_TYPE.TRIANGLE_STRIP:
                    wr.write_u32(len(_strip_extra))
                    wr.write_u32(stripIndex)
                    stripIndex += len(_strip_extra)

                    tri_strips.append(_strip_extra)

                wr.seek(start + 36)
                wr.write_vec3(prim.nbt)

        start = wr.tell()

        # triangle strips
        for vertex_groups in tri_strips:
            self.write_vertex_groups(wr, vertex_groups)

    def write_string_offset(self, wr, value, isShort = False):
        offset = 4294967295 # None type will always be 0xFFFFFFFF else use string pool
        if isShort:
            offset = 65535

        if value != None:
            pos = wr.tell()
            if value not in self._saved_strings:
                self._saved_strings[value] = []

            # save string, resolved at the end
            self._saved_strings[value].append((pos, isShort))

        if isShort:
            wr.write_u16(offset)
        else:
            wr.write_u32(offset)

    def write_target_offset(self, wr, offset_pos, relative_pos, is_short = False):
        origin = wr.tell()
        wr.seek(offset_pos)
        if is_short:
            wr.write_u16(origin - relative_pos)
        else:
            wr.write_u32(origin - relative_pos)
        wr.seek(origin)

    def write_objects(self, wr, objects):
        for obj in objects:
            obj.flag_props.apply_flag_properties()

            start = wr.tell()
            self.write_string_offset(wr, obj.name)
            wr.write_u32(obj.type)
            wr.write_u32(obj.constant_offset)
            wr.write_u32(obj.flag_props.flags)

            if obj.type == HSF_OBJECT_TYPE.LIGHT:
                self.write_light(wr, obj.data)
            elif obj.type == HSF_OBJECT_TYPE.CAMERA:
                self.write_camera(wr, obj.data)
            else:
                self.write_object_data(wr, obj, obj.data)

            # pad to fixed size
            end = wr.tell()
            pad = HsfObject.SIZE - (end - start)
            if pad > 0:
                wr.write_bytes(b'\xCC' * pad)

    def write_light(self, wr, data):
        wr.write_vec3(data.pos)
        wr.write_vec3(data.target)
        wr.write_u8(data.type)
        wr.write_u8(data.r)
        wr.write_u8(data.g)
        wr.write_u8(data.b)
        wr.write_f32(data.unk2C)
        wr.write_f32(data.ref_distance)
        wr.write_f32(data.ref_brightness)
        wr.write_f32(data.cutoff)
        wr.write_f32(0.0) # Extra 0 before padding starts

    def write_camera(self, wr, data):
        wr.write_vec3(data.pos)
        wr.write_vec3(data.target)
        wr.write_f32(data.aspect_dupe)
        wr.write_f32(data.fov)
        wr.write_f32(data.near)
        wr.write_f32(data.far)

    def write_object_data(self, wr,obj, data):
        wr.write_i32(data.parentIndex)
        wr.write_u32(data.childrenCount)
        wr.write_i32(data.childrenSymbolIndex)
        self.write_transform(wr, data.baseTransform)
        self.write_transform(wr, data.currentTransform)
        if obj.type == HSF_OBJECT_TYPE.REPLICA:
            wr.write_i32(data.replicaIndex)
            wr.write_f32(data.min[1])
            wr.write_f32(data.min[2])
        else:
            wr.write_vec3(data.min)
        wr.write_vec3(data.max)
        wr.write_f32(data.baseMorph)
        wr.write_f32s(data.morphWeights)
        wr.write_i32(data.faceIndex)
        wr.write_i32(data.vertexIndex)
        wr.write_i32(data.normalIndex)
        wr.write_i32(data.colorIndex)
        wr.write_i32(data.texCoordIndex)
        wr.write_u32(data.materialDataOffset)
        wr.write_i32(data.attributeIndex)
        wr.write_u8(data.clusterUpdatedRuntimeFlag)
        wr.write_u8(data.unknown3)
        wr.write_u8(data.shapeType)
        wr.write_u8(data.hiliteAnimFlags)
        wr.write_u32(data.shapeCount)
        wr.write_i32(data.shapeSymbolIndex)
        wr.write_u32(data.cluserCount)
        wr.write_i32(data.cluserSymbolIndex)
        wr.write_u32(data.envelopeCount)
        wr.write_i32(data.envelopeIndex)
        wr.write_u32(data.clusterPositionsOffset)
        wr.write_u32(data.clusterNormalsOffset)

    def write_transform(self, wr, transform):
        wr.write_vec3(transform.pos)
        wr.write_vec3(transform.rot)
        wr.write_vec3(transform.sca)

    def write_textures(self, wr, textures):
        start = wr.tell()

        # write motion headers
        for tex in textures:
            self.write_string_offset(wr, tex.name)
            wr.write_u32(tex.max_lod)
            wr.write_u8(tex.format)
            wr.write_u8(tex.bpp)
            wr.write_u16(tex.width)
            wr.write_u16(tex.height)
            wr.write_u16(tex.palette_count)
            wr.write_u32(tex.tint_color)
            wr.write_i32(tex.palette_index)
            wr.write_u32(tex.padd)
            wr.write_u32(0)

        data_start = wr.tell()
        for i in range(len(textures)):
            wr.align(32)
            self.write_target_offset(wr, start + i * 32 + 28, data_start)
            wr.write_bytes(textures[i].data)

    def write_palettes(self, wr, palettes):
        start = wr.tell()

        for pal in palettes:
            self.write_string_offset(wr, pal.name)
            wr.write_u32(pal.format)
            wr.write_u32(len(pal.data) // 2)
            wr.write_u32(0)

        data_start = wr.tell()
        # write motion headers
        for i in range(len(palettes)):
            wr.align(32)
            self.write_target_offset(wr, start + i * 16 + 12, data_start)
            for v in palettes[i].data:
                wr.write_u8(v)

    def write_motions(self, wr, motions):
        track_offset = 0

        # write motion headers
        for motion in motions:
            self.write_string_offset(wr, motion.name)
            wr.write_u32(len(motion.tracks))
            wr.write_u32(track_offset)
            wr.write_f32(motion.frame_count)

            track_offset += len(motion.tracks) * 48

        # write track headers
        for motion in motions:
            for track in motion.tracks:
                wr.write_u8(track.type)
                wr.write_u8(track.start)
                self.write_string_offset(wr, track.targetString, True)
                wr.write_i16(track.targetIndex)
                wr.write_u16(track.channel)
                wr.write_u16(track.interpolation)
                wr.write_u16(len(track.key_frames))

                if len(track.key_frames) > 0 and track.interpolation != 4:
                    track._key_offset_pos = wr.tell()
                    wr.write_u32(0) 
                else:
                    wr.write_f32(track.constant)

        # finally write key data
        key_data_start = wr.tell()
        for motion in motions:
            for track in motion.tracks:
                if len(track.key_frames) > 0 and track.interpolation != 4:
                    self.write_target_offset(wr, track._key_offset_pos, key_data_start)

                    for kf in track.key_frames:
                        if track.interpolation in (HSF_CURVE_TYPE.STEP, HSF_CURVE_TYPE.LINEAR): # Step / Linear
                            wr.write_f32(kf.frame)
                            wr.write_f32(kf.value)
                        elif track.interpolation == HSF_CURVE_TYPE.BEZIER: # Bezier
                            wr.write_f32(kf.frame)
                            wr.write_f32(kf.value)
                            wr.write_f32(kf.slope_in)
                            wr.write_f32(kf.slope_out)
                        elif track.interpolation == HSF_CURVE_TYPE.BITMAP: # Bitmap
                            wr.write_f32(kf.frame)
                            wr.write_u32(kf.value)

    def write_envelopes(self, wr, envelopes):
        start = wr.tell()
        for env in envelopes:
            wr.write_u32(0xCCCCCCCC)
            wr.write_u32(0)
            wr.write_u32(0)
            wr.write_u32(0)
            wr.write_u32(len(env.singleBinds))
            wr.write_u32(len(env.doubleBinds))
            wr.write_u32(len(env.multiBinds))
            wr.write_u32(env.vertexCount)
            wr.write_u32(env.copyCount)

        bindWeightPosition = wr.tell()
        doubleBindWeightSize = 0
        for env in envelopes:
            bindWeightPosition += len(env.singleBinds) * 12;
            bindWeightPosition += len(env.doubleBinds) * 16;
            bindWeightPosition += len(env.multiBinds) * 16;
            for bind in env.multiBinds:
                doubleBindWeightSize += bind.weightCount * 12;

        doubleBindWeightsOffset = bindWeightPosition;
        multiBindWeightsOffset = bindWeightPosition + doubleBindWeightSize;


        doubleBindWeightOffsetPos = []
        multiBindWeightOffsetPos = []

        indexDataPos = wr.tell()
        for i in range(len(envelopes)):
            self.write_target_offset(wr, start + 4 + (i * 36), indexDataPos)
            for bind in envelopes[i].singleBinds:
                wr.write_u32(bind.boneIndex)
                wr.write_i16(bind.positionIndex)
                wr.write_i16(bind.positionCount)
                wr.write_i16(bind.normalIndex)
                wr.write_i16(bind.normalCount)

            self.write_target_offset(wr, start + 8 + (i * 36), indexDataPos)
            for bind in envelopes[i].doubleBinds:
                wr.write_u32(bind.bone1)
                wr.write_u32(bind.bone2)
                wr.write_u32(bind.weightCount)

                doubleBindWeightOffsetPos.append(wr.tell())
                wr.write_u32(0)

            self.write_target_offset(wr, start + 12 + (i * 36), indexDataPos)
            for bind in envelopes[i].multiBinds:
                wr.write_u32(bind.weightCount)
                wr.write_i16(bind.positionIndex)
                wr.write_i16(bind.positionCount)
                wr.write_i16(bind.normalIndex)
                wr.write_i16(bind.normalCount)

                multiBindWeightOffsetPos.append(wr.tell())
                wr.write_u32(0)

                origin = wr.tell()

                wr.seek(multiBindWeightsOffset)
                for mw in bind.weights:
                    wr.write_u32(mw.boneIndex)
                    wr.write_f32(mw.weight)

                multiBindWeightsOffset = wr.tell()

                wr.seek(origin)

                origin = wr.tell()

        data_start = wr.tell()

        doubleBindIdx = 0
        multiBindIdx = 0
        for i in range(len(envelopes)):
            for bind in envelopes[i].doubleBinds:
                self.write_target_offset(wr, doubleBindWeightOffsetPos[doubleBindIdx], data_start)
                doubleBindIdx += 1

                for dw in bind.weights:
                    wr.write_f32(dw.weight)
                    wr.write_i16(dw.positionIndex)
                    wr.write_i16(dw.positionCount)
                    wr.write_i16(dw.normalIndex)
                    wr.write_i16(dw.normalCount)

            for bind in envelopes[i].multiBinds:
                self.write_target_offset(wr, multiBindWeightOffsetPos[multiBindIdx], data_start)
                multiBindIdx += 1

                for mw in bind.weights:
                    wr.write_u32(mw.boneIndex)
                    wr.write_f32(mw.weight)

    def write_skeletons(self, wr, skeletons):
        for skel in skeletons:
            self.write_string_offset(wr, skel.name)
            self.write_transform(wr, skel.transform)

    def write_parts(self, wr, parts):
        data_idx = 0
        for part in parts:
            self.write_string_offset(wr, part.name)
            wr.write_u32(len(part.data))
            wr.write_u32(data_idx)
            data_idx += len(part.data)

        for part in parts:
            wr.write_u16s(part.data)

    def write_clusters(self, wr, clusters):
        for cluster in clusters:
            if len(cluster.weights) != 32:
                raise ValueError(f"Invalid cluster weight count {len(cluster.weights)}, expected 32!. ")

            self.write_string_offset(wr, cluster.name1)
            self.write_string_offset(wr, cluster.name2)
            self.write_string_offset(wr, cluster.target)
            wr.write_u32(cluster.partIdx)
            wr.write_f32(cluster.baseMorph)
            wr.write_f32s(cluster.weights)
            wr.write_bool(cluster.isAdjusted)
            wr.write_u8(cluster.unknown)
            wr.write_u16(cluster.type)
            wr.write_u32(cluster.bufferCount)
            wr.write_u32(cluster.bufferSymbolIdx)

    def write_shapes(self, wr, shapes):
        for shape in shapes:
            self.write_string_offset(wr, shape.name)
            wr.write_u16(shape.unknown)
            wr.write_u16(shape.bufferCount)
            wr.write_u32(shape.bufferSymbolIdx)

    def write_map_attributes(self, wr, map_attributes):
        data_idx = 0
        for map_attr in map_attributes:
            wr.write_f32(map_attr.minX)
            wr.write_f32(map_attr.minY)
            wr.write_f32(map_attr.minZ)
            data_idx_positions.append(wr.tell())
            wr.write_u32(data_idx)  # data index
            wr.write_u16(len(map_attr.data))
            data_idx += len(map_attr.data)

        for map_attr in map_attributes:
            wr.write_u16s(map_attr.data)

    def write_matrix_list(self, wr, matrix_list):
        for mat in matrix_list:
            wr.write_u32(len(mat.meshMatrices))
            wr.write_u32(len(mat.nodeMatrices))
            wr.write_u32(0)
            self.write_matrices(wr, mat.meshMatrices)
            self.write_matrices(wr, mat.nodeMatrices)
            self.write_matrices(wr, mat.allMatrices)

    def write_matrices(self, wr, matrices):
        for mat in matrices:
            wr.write_u32(mat.base_idx)
            wr.write_u32(mat.count)
            wr.write_f32s(mat.data)

    def write_symbols(self, wr, symbols):
        wr.write_u32s(symbols)

def hsf_to_json(hsf: HsfFile, indent: int = 2) -> str:
    data = hsf_to_dict(hsf)
    return json.dumps(data, indent=indent, ensure_ascii=False)

def hsf_to_dict(obj: Any) -> Any:
    """Recursively convert HSF objects to JSON-serializable dicts."""
    if obj is None:
        return None
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [hsf_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: hsf_to_dict(v) for k, v in obj.items()}

    # Handle custom classes
    if hasattr(obj, "__dict__") or is_dataclass(obj):
        result = {}

        # Special handling for flags
        if hasattr(obj, "flag_props") and obj.flag_props is not None:
            result["flags"] = obj.flag_props.flags
            # You can also include the boolean properties if you want readability
            if hasattr(obj.flag_props, "has_billboard"):
                for attr in ["has_billboard", "show_all_faces", "has_shadow",
                             "has_shadow_map", "has_lightmap", "depth_write",
                             "is_visible", "alpha_test", "mat_hook", "reflect_model"]:
                    if hasattr(obj.flag_props, attr):
                        result[attr] = getattr(obj.flag_props, attr)

        # Handle HsfAttribute flags
        if hasattr(obj, "use_nearest_filter"):
            result["use_nearest_filter"] = obj.use_nearest_filter
            result["use_mipmap_lod"] = obj.use_mipmap_lod
            result["use_hilte_reflect"] = obj.use_hilte_reflect

        # Main data
        for attr, value in vars(obj).items():
            if attr.startswith("_") or attr in ("flag_props",):
                continue
            result[attr] = hsf_to_dict(value)

        return result

    if isinstance(obj, ctypes.Array):
        return list(obj)

    if isinstance(obj, IntEnum):
        return int(obj)

    return str(obj)  # fallback