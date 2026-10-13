from mathutils import Matrix
import ctypes
import bpy
import gpu
import numpy as np
from bpy_extras.image_utils import load_image
from gpu_extras.batch import batch_for_shader
from gpu import state
import struct
from enum import IntEnum

DDS_MAGIC = b'DDS '

# flags
DDSD_MIPMAPCOUNT = 0x20000
DDSCAPS2_CUBEMAP = 0x200

# Pixel format flags
DDPF_FOURCC = 0x4
DDPF_RGB = 0x40
DDPF_RGBA = 0x41

FOURCC_DX10 = b'DX10'

# Types not in bgl
GL_COMPRESSED_RGBA_S3TC_DXT1_EXT = 0x83F1
GL_COMPRESSED_RGBA_S3TC_DXT3_EXT = 0x83F2
GL_COMPRESSED_RGBA_S3TC_DXT5_EXT = 0x83F3

GL_COMPRESSED_RED_RGTC1 = 0x8DBB
GL_COMPRESSED_RG_RGTC2 = 0x8DBD

GL_R11F_G11F_B10F = 0x8C3A
GL_UNSIGNED_INT_10F_11F_11F_REV = 0x8C3B

GL_RG16F = 0x822F
GL_RG = 0x8227
GL_HALF_FLOAT = 0x140B

class DXGI_FORMAT(IntEnum):
    UNKNOWN = 0
    R8_UNORM = 61
    R8G8_UNORM = 49
    R8G8B8A8_UNORM = 28
    R8G8B8A8_UNORM_SRGB = 29

    R16_UNORM = 56
    R16_FLOAT = 54
    R16G16_UNORM = 35
    R16G16_FLOAT = 34
    R16G16B16A16_UNORM = 11
    R16G16B16A16_FLOAT = 10

    R32_FLOAT = 41
    R32G32_FLOAT = 16
    R32G32B32_FLOAT = 6
    R32G32B32A32_FLOAT = 2

    R11G11B10_FLOAT = 26
    R10G10B10A2_UNORM = 24

    BC1_UNORM = 71
    BC1_UNORM_SRGB = 72
    BC2_UNORM = 74
    BC2_UNORM_SRGB = 75
    BC3_UNORM = 77
    BC3_UNORM_SRGB = 78
    BC4_UNORM = 80
    BC5_UNORM = 83
    BC6H_UF16 = 95
    BC6H_SF16 = 96
    BC7_UNORM = 98
    BC7_UNORM_SRGB = 99

DXGI_TO_GPU = {
    DXGI_FORMAT.R8_UNORM: 'R8',
    DXGI_FORMAT.R16_FLOAT: 'R16F',
    DXGI_FORMAT.R32_FLOAT: 'R32F',
    DXGI_FORMAT.R8G8_UNORM: 'RG8',
    DXGI_FORMAT.R16G16_FLOAT: 'RG16F',
    DXGI_FORMAT.R32G32_FLOAT: 'RG32F',
    DXGI_FORMAT.R8G8B8A8_UNORM: 'RGBA8',
    DXGI_FORMAT.R16G16B16A16_FLOAT: 'RGBA16F',
    DXGI_FORMAT.R32G32B32A32_FLOAT: 'RGBA32F',
    DXGI_FORMAT.R11G11B10_FLOAT: 'R11F_G11F_B10F',
}

class DDSHeader:
    def __init__(self):
        self.width = 0
        self.height = 0
        self.depth = 1
        self.mip_count = 1
        self.fourcc = None
        self.dxgi_format = None
        self.array_size = 1
        self.is_cubemap = False

def read_dds(path):
    with open(path, "rb") as f:
        if f.read(4) != DDS_MAGIC:
            raise ValueError("Not a DDS file")

        header = parse_dds_header(f)
        return header

def is_block_compressed(fmt):
    return fmt in {
        DXGI_FORMAT.BC1_UNORM,
        DXGI_FORMAT.BC2_UNORM,
        DXGI_FORMAT.BC3_UNORM,
        DXGI_FORMAT.BC4_UNORM,
        DXGI_FORMAT.BC5_UNORM,
        DXGI_FORMAT.BC7_UNORM,
    }


def get_block_size(fmt):
    if fmt in (DXGI_FORMAT.BC1_UNORM, DXGI_FORMAT.BC4_UNORM):
        return 8
    return 16


def mip_size(w, h, fmt):
    if is_block_compressed(fmt):
        bw = max(1, (w + 3) // 4)
        bh = max(1, (h + 3) // 4)
        return bw * bh * get_block_size(fmt)
    else:
        return w * h * get_bytes_per_pixel(fmt)

def get_bytes_per_pixel(fmt):
    block_compressed = {
        DXGI_FORMAT.BC1_UNORM: 8,
        DXGI_FORMAT.BC1_UNORM_SRGB: 8,
        DXGI_FORMAT.BC4_UNORM: 8,
        DXGI_FORMAT.BC2_UNORM: 16,
        DXGI_FORMAT.BC2_UNORM_SRGB: 16,
        DXGI_FORMAT.BC3_UNORM: 16,
        DXGI_FORMAT.BC3_UNORM_SRGB: 16,
        DXGI_FORMAT.BC5_UNORM: 16,
        DXGI_FORMAT.BC6H_UF16: 16,
        DXGI_FORMAT.BC6H_SF16: 16,
        DXGI_FORMAT.BC7_UNORM: 16,
        DXGI_FORMAT.BC7_UNORM_SRGB: 16,
    }
    uncompressed = {
        DXGI_FORMAT.R8_UNORM: 1,
        DXGI_FORMAT.R8G8_UNORM: 2,
        DXGI_FORMAT.R8G8B8A8_UNORM: 4,
        DXGI_FORMAT.R8G8B8A8_UNORM_SRGB: 4,
        DXGI_FORMAT.R16_UNORM: 2,
        DXGI_FORMAT.R16_FLOAT: 2,
        DXGI_FORMAT.R16G16_UNORM: 4,
        DXGI_FORMAT.R16G16_FLOAT: 4,
        DXGI_FORMAT.R16G16B16A16_UNORM: 8,
        DXGI_FORMAT.R16G16B16A16_FLOAT: 8,
        DXGI_FORMAT.R32_FLOAT: 4,
        DXGI_FORMAT.R32G32_FLOAT: 8,
        DXGI_FORMAT.R32G32B32_FLOAT: 12,
        DXGI_FORMAT.R32G32B32A32_FLOAT: 16,
        DXGI_FORMAT.R11G11B10_FLOAT: 4,
        DXGI_FORMAT.R10G10B10A2_UNORM: 4,
    }

    if fmt in block_compressed:
        return block_compressed[fmt]

    if fmt in uncompressed:
        return uncompressed[fmt]

    return 0

def parse_dds_header(f):
    hdr = DDSHeader()
    # header data
    header_bytes = f.read(124)
    (
        size, 
        flags, 
        height, 
        width, 
        pitch, 
        depth, 
        mip_count,
        *reserved1
    ) = struct.unpack("<I I I I I I I 11II", header_bytes[:76])

    hdr.width = width
    hdr.height = height
    hdr.mip_count = mip_count if (flags & DDSD_MIPMAPCOUNT) else 1
    hdr.depth = max(depth, 1)
    # pf header
    pf_offset = 72
    pf = header_bytes[pf_offset:pf_offset + 32]
    (
        pf_size, 
        pf_flags, 
        fourcc, 
        rgb_bits,
        r_mask,
        g_mask, 
        b_mask, 
        a_mask
    ) = struct.unpack("<I I 4s I I I I I", pf)

    hdr.fourcc = fourcc.decode("ascii", errors="ignore")
    print("fourcc")
    print(str(hdr.fourcc))
    print(str(pf_size))
    print(str(hdr.width))
    print(str(hdr.height))

    # Cap flags
    caps_offset = pf_offset + 32
    caps = header_bytes[caps_offset:caps_offset + 20]

    caps1, caps2, caps3, caps4, reserved2 = struct.unpack("<5I", caps)

    hdr.is_cubemap = bool(caps2 & DDSCAPS2_CUBEMAP)

    # DX10 header
    if fourcc == FOURCC_DX10:
        parse_dx10_header(f, hdr)
    else:
        hdr.dxgi_format = convert_fourcc_to_dxgi(hdr.fourcc)

    return hdr


def parse_dx10_header(f, hdr):
    (
        dxgi_format,
        resource_dimension,
        misc_flag,
        array_size,
        misc_flags2
    ) = struct.unpack("<I I I I I", f.read(20))

    hdr.dxgi_format = DXGI_FORMAT(dxgi_format)
    hdr.array_size = array_size


def convert_fourcc_to_dxgi(fourcc):
    return {
        "DXT1": DXGI_FORMAT.BC1_UNORM,
        "DXT3": DXGI_FORMAT.BC2_UNORM,
        "DXT5": DXGI_FORMAT.BC3_UNORM,
        "ATI1": DXGI_FORMAT.BC4_UNORM,
        "BC4U": DXGI_FORMAT.BC4_UNORM,
        "ATI2": DXGI_FORMAT.BC5_UNORM,
        "BC5U": DXGI_FORMAT.BC5_UNORM,
    }.get(fourcc, DXGI_FORMAT.R8G8B8A8_UNORM)

def load_as_gpu_image(path):
    hdr = read_dds(path)
    if hdr.dxgi_format not in DXGI_TO_GPU:
        raise RuntimeError(f"Unsupported DDS format: {hdr.dxgi_format}")

    w, h = hdr.width, hdr.height
    d = max(1, hdr.depth)

    gpu_format = DXGI_TO_GPU[hdr.dxgi_format]
    with open(path, "rb") as f:
        f.seek(128 + (20 if hdr.fourcc == "DX10" else 0))
        size = mip_size(w, h, hdr.dxgi_format) * d
        raw = f.read(size)
        print(str(gpu_format))

        if gpu_format == 'RGBA8':
            arr = np.frombuffer(raw, dtype=np.uint8)
            arr = arr.astype(np.float32) * (1.0 / 255.0)

            buffer = gpu.types.Buffer('FLOAT', arr.size, arr)
            gpuImage = gpu.types.GPUTexture(size=(w, h),
                                            format='RGBA32F',
                                            data=buffer)

        if gpu_format == 'RGBA32F':
            arr = np.frombuffer(raw, dtype=np.float32)
            buffer = gpu.types.Buffer('FLOAT', arr.size, arr)
            gpuImage = gpu.types.GPUTexture(size=(w, h),
                                            format=gpu_format,
                                            data=buffer)

        if gpu_format == 'R11F_G11F_B10F':
            packed = np.frombuffer(raw, dtype=np.uint32)
            arr = r11g11b10_array_to_rgba32f(packed)
            buffer = gpu.types.Buffer('FLOAT', arr.size, arr)
            gpuImage = gpu.types.GPUTexture(size=(w, h),
                                            format='RGBA32F',
                                            data=buffer)
        if gpu_format == 'RGBA16F':
            arr16 = np.frombuffer(raw, dtype=np.float16)
            arr32 = arr16.astype(np.float32)

            buffer = gpu.types.Buffer('FLOAT', arr32.size, arr32)
            gpuImage = gpu.types.GPUTexture(size=(w, h),
                                            format='RGBA16F',
                                            data=buffer)
        if gpu_format == 'RG16F':
            arr16 = np.frombuffer(raw, dtype=np.float16)
            arr32 = arr16.astype(np.float32)

            buffer = gpu.types.Buffer('FLOAT', arr32.size, arr32)
            gpuImage = gpu.types.GPUTexture(size=(w, h),
                                            format='RG16F',
                                            data=buffer)
        if gpu_format == 'R16F':
            arr16 = np.frombuffer(raw, dtype=np.float16)
            arr32 = arr16.astype(np.float32)

            buffer = gpu.types.Buffer('FLOAT', arr32.size, arr32)
            gpuImage = gpu.types.GPUTexture(size=(w, h),
                                            format='R16F',
                                            data=buffer)

        return gpuImage
