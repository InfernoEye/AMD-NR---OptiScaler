#!/usr/bin/env python3
"""Generate a small original launcher icon using only Python stdlib."""
from pathlib import Path
import struct
import zlib
import sys

size = 128
pixels = bytearray()
for y in range(size):
    pixels.append(0)
    for x in range(size):
        border = 4 <= x < 124 and 4 <= y < 124
        highlight = ((x - 64) ** 2 + (y - 64) ** 2 < 38 ** 2)
        neural = abs(x - y) < 5 or abs(x + y - 127) < 5
        if not border:
            rgb = (10, 15, 23)
        elif neural and highlight:
            rgb = (224, 75, 84)
        elif highlight:
            rgb = (30, 43, 62)
        else:
            rgb = (18, 26, 37)
        pixels.extend(rgb + (255,))

def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(
        ">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

header = b"\x89PNG\r\n\x1a\n"
ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
target = Path(sys.argv[1] if len(sys.argv) > 1 else "amdnr-linux.png")
target.write_bytes(header + chunk(b"IHDR", ihdr) +
                   chunk(b"IDAT", zlib.compress(bytes(pixels), 9)) +
                   chunk(b"IEND", b""))
