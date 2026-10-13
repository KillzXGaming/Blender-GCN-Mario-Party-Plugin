import struct

class BinaryReader():
	
    def __init__(self, f, endian="<"):
       self.f = f
       self.endian = endian

    def set_endian(self, endian):
        self.endian = endian

    def seek(self, offset, whence=0):
        self.f.seek(offset, whence)

    def skip(self, size):
        self.f.seek(size, 1)

    def tell(self):
        return self.f.tell()

    def align(self, alignment):
        pos = self.tell()
        padding = (-pos) % alignment
        if padding:
            self.f.seek(padding, 1)

    def _read(self, fmt):
        size = struct.calcsize(fmt)
        data = self.f.read(size)
        if len(data) != size:
            raise EOFError("Unexpected end of file")
        return struct.unpack(self.endian + fmt, data)[0]

    def _read_struct(self, fmt):
        size = struct.calcsize(fmt)
        data = self.f.read(size)
        if len(data) != size:
            raise EOFError("Unexpected end of file")
        return struct.unpack(self.endian + fmt, data)

    def read_signature(self, expected):
        sig = self.read_bytes(len(expected))
        return sig == expected

    def read_value(self, valueOffset, valueType):
        pos = self.f.tell()

        self.seek(valueOffset)
        value = valueType()
        value.read(self)

        self.seek(pos)
        return value

    def read_vec2(self):
        return (self._read("f"), self._read("f"))

    def read_vec3(self):
        return (self._read("f"), self._read("f"), self._read("f"))

    def read_vec4(self):
        return (self._read("f"), self._read("f"), self._read("f"), self._read("f"))

    def read_color8(self):
        r = self.read_u8()
        g = self.read_u8()
        b = self.read_u8()
        a = self.read_u8()
        return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)

    def read_8_8_8_snorm(self):
        x = self.read_s8()
        y = self.read_s8()
        z = self.read_s8()
        return (x / 127.0, y / 127.0, z / 127.0)

    def read_i32(self):
        return self._read("i")

    def read_u32(self):
        return self._read("I")

    def read_f32(self):
        return self._read("f")

    def read_u16(self):
        return self._read("H")

    def read_i16(self):
        return self._read("h")

    def read_u64(self):
        return self._read("Q")

    def read_i64(self):
        return self._read("q")

    def read_u8(self):
        return self.f.read(1)[0]

    def read_s8(self):
        return self._read("b")

    def read_bool(self):
        return struct.unpack("?", self.f.read(1))[0]

    def read_u16s(self, count):
        values = []
        for i in range(count):
            values.append(self.read_u16())
        return values

    def read_u32s(self, count):
        values = []
        for i in range(count):
            values.append(self.read_u32())
        return values

    def read_f32s(self, count):
        values = []
        for i in range(count):
            values.append(self.read_f32())
        return values

    def read_bytes(self, n):
        data = self.f.read(n)
        if len(data) != n:
            raise EOFError("Unexpected end of file")
        return data

    def read_cstring_offset_list(self, count, encoding="utf-8"):
        strings = []
        for i in range(count):
            strings.append(self.read_cstring_offset(encoding))
        return strings

    def read_cstring_offset(self, encoding="utf-8"):
        offset = self.read_u64()
        pos = self.f.tell()

        result = ""
        if offset:
            self.f.seek(offset + 2, 0)
            result = self.read_cstring()

        self.f.seek(pos, 0)
        return result

    def read_cstring(self, encoding="utf-8"):
        chars = bytearray()
        while True:
            b = self.f.read(1)
            if not b:
                raise EOFError("Unexpected EOF while reading string")
            if b == b"\x00":
                break
            chars += b
        return chars.decode(encoding)

    def read_string_u32(self, encoding="utf-8"):
        length = self.read_u32()
        return self.read_bytes(length).decode(encoding)

class BinaryWriter:
    def __init__(self, f, endian="<"):
        self.f = f
        self.endian = endian

    def _write(self, fmt, value):
        self.f.write(struct.pack(self.endian + fmt, value))

    def _write_struct(self, fmt, values):
        self.f.write(struct.pack(self.endian + fmt, *values))

    def seek(self, offset, whence=0):
        self.f.seek(offset, whence)

    def tell(self):
        return self.f.tell()

    def align(self, alignment, pad=b"\x00"):
        pos = self.tell()
        padding = (-pos) % alignment
        if padding:
            self.f.write(pad * padding)

    def write_color8(self, v):
        self.write_byte_unorm(int(v[0] * 255))
        self.write_byte_unorm(int(v[1] * 255))
        self.write_byte_unorm(int(v[2] * 255))
        self.write_byte_unorm(int(v[3] * 255))

    def write_byte_unorm(self, v):
        byte_val = max(0, min(255, v)) 
        self._write("B", byte_val)

    def write_byte_snorm(self, v):
        byte_val = max(-128, min(128, v)) 
        self._write("b", byte_val)

    def write_byte(self, v):
        self._write("B", byte_val)
        
    def write_u8(self, v):
        byte_val = max(0, min(255, v)) 
        self._write("B", byte_val)

    def write_bytes(self, n):
        self.f.write(n)

    def write_sbyte(self, v):
        self._write("b", byte_val)

    def write_u32(self, v):
        self._write("I", v)

    def write_i32(self, v):
        self._write("i", v)

    def write_f32(self, v):
        self._write("f", v)

    def write_vec2(self, v):
        self._write("f", v[0])
        self._write("f", v[1])

    def write_vec3(self, v):
        self._write("f", v[0])
        self._write("f", v[1])
        self._write("f", v[2])

    def write_vec4(self, v):
        self._write("f", v[0])
        self._write("f", v[1])
        self._write("f", v[2])
        self._write("f", v[3])

    def write_u16(self, v):
        self._write("H", v)

    def write_i16(self, v):
        self._write("h", v)

    def write_u64(self, v):
        self._write("Q", v)

    def write_i64(self, v):
        self._write("q", v)

    def write_byte(self, v):
        self._write("c", v)

    def write_bool(self, v):
        self._write("?", v)

    def write_8_8_8_snorm(self, v):
        self.write_byte_snorm(int(v[0] * 127.0))
        self.write_byte_snorm(int(v[1] * 127.0))
        self.write_byte_snorm(int(v[2] * 127.0))

    def write_u16s(self, values):
        for v in values:
            self.write_u16(v)

    def write_u32s(self, values):
        for v in values:
            self.write_u32(v)

    def write_f32s(self, values):
        for v in values:
            self.write_f32(v)

    def write_magic(self, s, encoding="utf-8"):
        self.f.write(s.encode(encoding))

    def write_cstring(self, s, encoding="utf-8"):
        self.f.write(s.encode(encoding))
        self.f.write(b"\x00")

    def write_string_u32(self, s, encoding="utf-8"):
        data = s.encode(encoding)
        self.write_u32(len(data))
        self.f.write(data)

    def write_target_offset(self, offset_pos, relative_pos, is_short = False):
        origin = self.tell()
        self.seek(offset_pos)
        if is_short:
            self.write_u16(origin - relative_pos)
        else:
            self.write_u32(origin - relative_pos)
        self.seek(origin)