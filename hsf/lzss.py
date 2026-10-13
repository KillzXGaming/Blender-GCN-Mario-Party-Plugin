import ctypes
import os
from pathlib import Path
import sys
from ctypes import POINTER, c_uint8, c_size_t
from sys import platform

base_dir = os.path.dirname(os.path.abspath(__file__))
lib_dir = os.path.join(base_dir, "lib")

if sys.platform.startswith("linux"):
    lib_name = "liblzss.so"
elif sys.platform.startswith("darwin"):
    lib_name = "lzss.dylib"
else:
    lib_name = "lzss.dll"

lib_path = os.path.join(lib_dir, lib_name)
lib = ctypes.CDLL(str(lib_path))

lib.EncodeLZSS.argtypes = [POINTER(c_uint8), POINTER(c_uint8), c_size_t]
lib.EncodeLZSS.restype = c_size_t

def compress_lzss(src_bytes: bytes) -> bytes:
    src_len = len(src_bytes)
    max_out = src_len + src_len // 8 + 64
    dst_buf = (ctypes.c_ubyte * max_out)()

    src_array = (ctypes.c_ubyte * src_len).from_buffer_copy(src_bytes)
    out_len = ctypes.c_size_t()

    compressed_size = lib.EncodeLZSS(dst_buf, src_array, src_len)
    compressed = bytes(dst_buf[:compressed_size])
    return compressed
    
def compress_file(input:Path, output:Path):
    data = input.read_bytes()
    compressed = compress_lzss(data)
    output.write_bytes(compressed)