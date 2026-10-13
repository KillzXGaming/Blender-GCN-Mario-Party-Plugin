import ctypes
import zlib
import os
import struct
import io
from . io_util import *
from . lzss import compress_lzss
import glob

def read_u8(f):
    return struct.unpack('>B', f.read(1))[0]

def read_u32(f):
    return struct.unpack('>I', f.read(4))[0]

def decode_lzss(f, raw_size):
    window = bytearray(1024)
    window_ofs = 958
    flag = 0
    dst = bytearray(raw_size)
    dst_idx = 0

    while dst_idx < raw_size:
        flag >>= 1
        if not (flag & 0x100):
            flag = 0xFF00 | read_u8(f)
        if flag & 0x1:
            byte = read_u8(f)
            window[window_ofs] = byte
            window_ofs = (window_ofs + 1) % 1024
            dst[dst_idx] = byte
            dst_idx += 1
        else:
            byte1 = read_u8(f)
            byte2 = read_u8(f)
            ofs = ((byte2 & 0xC0) << 2) | byte1
            copy_len = (byte2 & 0x3F) + 3
            for i in range(copy_len):
                byte = window[(ofs + i) % 1024]
                window[window_ofs] = byte
                window_ofs = (window_ofs + 1) % 1024
                dst[dst_idx] = byte
                dst_idx += 1
    return bytes(dst)


def decode_slide(f, raw_size):
    _temp_len = read_u32(f) 
    num_bits = 0
    mask = 0
    dst = bytearray(raw_size)
    dst_idx = 0

    while dst_idx < raw_size:
        if num_bits == 0:
            mask = read_u32(f)
            num_bits = 32
        if mask & 0x80000000:
            dst[dst_idx] = read_u8(f)
            dst_idx += 1
        else:
            hi = read_u8(f)
            lo = read_u8(f)
            copy_ofs = (hi << 8) | lo
            copy_len = (copy_ofs & 0xF000) >> 12
            copy_ofs &= 0xFFF
            lookback_idx = dst_idx - copy_ofs

            if copy_len == 0:
                copy_len = read_u8(f) + 18
            else:
                copy_len += 2

            for _ in range(copy_len):
                if lookback_idx - 1 < 0:
                    b = 0
                else:
                    b = dst[lookback_idx - 1]
                dst[dst_idx] = b
                dst_idx += 1
                lookback_idx += 1
        mask <<= 1
        num_bits -= 1
    return bytes(dst)


def decode_rle(f, raw_size):
    dst = bytearray(raw_size)
    dst_idx = 0
    remaining = raw_size

    while remaining > 0:
        len_value = read_u8(f)
        if len_value < 128:
            value = read_u8(f)
            for _ in range(len_value):
                dst[dst_idx] = value
                dst_idx += 1
        else:
            len_value -= 128
            for _ in range(len_value):
                dst[dst_idx] = read_u8(f)
                dst_idx += 1
        remaining -= len_value
    return bytes(dst)


def decode_zlib(f, _ignored_len):
    inner_raw_size = read_u32(f)
    pack_size = read_u32(f)
    pack_buf = f.read(pack_size)

    decompressor = zlib.decompressobj(wbits=15 + 32)
    decompressed = decompressor.decompress(pack_buf)
    return decompressed

def compress_rle(data: bytes) -> bytes:
    if not data:
        return b''
    output = bytearray()
    i = 0
    while i < len(data):
        curr = data[i]
        if i + 1 < len(data) and curr == data[i + 1]:
            run_len = 1
            while run_len < 127 and i + run_len < len(data) and data[i + run_len] == curr:
                run_len += 1
            output.append(run_len)
            output.append(curr)
            i += run_len
        else:
            lit_len = 0
            while (lit_len < 127 and
                   i + lit_len < len(data) and
                   (i + lit_len + 1 >= len(data) or data[i + lit_len] != data[i + lit_len + 1])):
                lit_len += 1
            output.append(0x80 | lit_len)
            output.extend(data[i:i + lit_len])
            i += lit_len
    return bytes(output)

def compress_inflate(data: bytes) -> bytes:
    if not data:
        return b''
    return zlib.compress(data, level=9)

def compress_slide(data: bytes) -> bytes:
    return b"" # TODO

class FileEntry:
    def __init__(self):
        self.data = None
        self.name:str = ""
        self.comp_type = 0

    def export(self, file_path):
        with open(file_path, 'wb') as f:
            f.write(self.data)

    def get_extension(self):
        with io.BytesIO(self.data) as f:
            sig = f.read(3)
            if sig == b"HSF":
                return ".hsf"
            if sig == b"ATB":
                return ".atb"
        return ".bin"

class BinFile:

    def __init__(self):
        self.files:List[FileEntry] = []

    @classmethod
    def load(cls, filePath):
        with open(filePath, 'rb') as f:
            reader = BinaryReader(f, endian=">")
            instance = cls()
            instance.read(reader)
            return instance

    def save(self, filePath):
        with open(filePath, 'wb') as f:
            self.write(BinaryWriter(f, ">"))

    def add_file(self, data):
        file = FileEntry()
        file.data = data
        self.files.append(file)

    def load_folder(self, folder_path):
        order_file = folder_path / "order.txt"
        if not order_file.is_file():
            return

        with open(folder_path / "order.txt", "r") as r:
            for line in r:
                values = line.split("=")
                if len(values) != 2:
                    continue

                file_path = folder_path / values[0]
                # add dummy data
                if not file_path.is_file():
                    file = FileEntry()
                    file.data = [32]
                    self.files.append(file)
                    continue

                file = FileEntry()
                file.data = file_path.read_bytes() 
                self.files.append(file)

    def read(self, r):
        file_count = r.read_u32()
        file_offsets = [r.read_u32() for _ in range(file_count)]

        for i in range(file_count):
            file = FileEntry()
            self.files.append(file)

            r.seek(file_offsets[i])
            raw_size  = r.read_u32()
            comp_type  = r.read_u32()

            bin_file = r.f
            if comp_type == 1:
                comp_type_str = "lzss"
                decomp_buf = decode_lzss(bin_file, raw_size)
            elif comp_type in (2, 3, 4):
                comp_type_str = "slide"
                decomp_buf = decode_slide(bin_file, raw_size)
            elif comp_type == 5:
                comp_type_str = "rle"
                decomp_buf = decode_rle(bin_file, raw_size)
            elif comp_type == 7:
                comp_type_str = "zlib"
                decomp_buf = decode_zlib(bin_file, raw_size)
            else:
                comp_type_str = ""
                decomp_buf = bin_file.read(raw_size)

            file.comp_type = comp_type
            file.data = decomp_buf
            file.name = f"file{i}.{comp_type_str}.{file.get_extension()}"

    def write(self, wr):
        wr.write_u32(len(self.files))
        for i in range(len(self.files)):
            wr.write_u32(0) # reserve offset space

        for i, file in enumerate(self.files):
            print(file.name)
            raw_data = file.data
            comp_type = file.comp_type
            comp_type = 1

            # resolve offset
            wr.align(4)
            wr.write_target_offset(4 + i * 4, 0)
            # decomp size
            wr.write_u32(len(raw_data))
            # compression type
            wr.write_u32(comp_type)

            if comp_type in (2, 3, 4): # SLIDE 
                wr.write_u32(len(raw_data)) # extra decomp size
                compressed = compress_slide(raw_data)
            elif comp_type == 7: # ZLIB (MP5 and later games only)
                wr.write_u32(len(raw_data)) # extra decomp size
                compressed = compress_inflate(raw_data)
                wr.write_u32(len(compressed)) #comp size
            elif comp_type == 1: # LZSS
                compressed = compress_lzss(raw_data)
            elif comp_type == 5: # RLE
                compressed = compress_rle(raw_data)
            else:
                compressed = raw_data

            wr.write_bytes(compressed)
