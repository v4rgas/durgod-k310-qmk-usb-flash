#!/usr/bin/env python3
"""Patch the vector checksum at 0x1C so the first eight words sum to zero."""
import struct
import sys

src, dst = sys.argv[1:3]
image = bytearray(open(src, "rb").read())
words = struct.unpack_from("<7I", image, 0)
struct.pack_into("<I", image, 0x1C, -sum(words) & 0xFFFFFFFF)
assert sum(struct.unpack_from("<8I", image, 0)) & 0xFFFFFFFF == 0
open(dst, "wb").write(image)
print("%s: %d bytes" % (dst, len(image)))
