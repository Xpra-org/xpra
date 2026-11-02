# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# detect the image type from the header of the data,
# kept free of any `PIL` dependency so it can be used to validate
# untrusted data before handing it to an image loader

import struct
from collections.abc import Callable

from xpra.common import SizedBuffer
from xpra.util.str_fn import memoryview_to_bytes

PNG_HEADER = struct.pack("BBBBBBBB", 137, 80, 78, 71, 13, 10, 26, 10)
HEADER_SIZE = 256


def is_png(data: bytes) -> bool:
    return data.startswith(PNG_HEADER)


def is_apng(data: SizedBuffer) -> bool:
    # an animated PNG has an `acTL` chunk before the first `IDAT`,
    # which may come after other chunks (ie: `iCCP`), so walk the chunks in the whole buffer:
    pos = len(PNG_HEADER)
    while pos + 8 <= len(data):
        length, ctype = struct.unpack_from(">I4s", data, pos)
        if ctype == b"acTL":
            return True
        if ctype in (b"IDAT", b"IEND"):
            return False
        pos += 12 + length
    return False


RIFF_HEADER = b"RIFF"
WEBP_HEADER = b"WEBP"


def is_webp(data: bytes) -> bool:
    return data[:4] == RIFF_HEADER and data[8:12] == WEBP_HEADER


JPEG_HEADER = struct.pack("BBB", 0xFF, 0xD8, 0xFF)


def is_jpeg(data: bytes) -> bool:
    # the jpeg header is actually more complicated than this,
    # but in practice all the data we receive from the server
    # will have this type of header
    return data[:3] == JPEG_HEADER


def is_svg(data: bytes) -> bool:
    if data.startswith(b"<!--"):
        try:
            data = data.split(b"-->", 1)[1].strip(b"\n\r ")
        except IndexError:
            pass
    # ie: breeze icons start with `<!DOCTYPE svg>`:
    return data[:5] == b"<?xml" or data[:4] == b"<svg" or data[:13] == b"<!DOCTYPE svg"


XPM_HEADER = b"/* XPM */"


def is_xpm(data: bytes) -> bool:
    return data[:9] == XPM_HEADER


def is_tiff(data: bytes) -> bool:
    if data[:2] == b"II":
        return data[2] == 42 and data[3] == 0
    if data[:2] == b"MM":
        return data[2] == 0 and data[3] == 42
    return False


BMP_HEADER = b"BM"
BMP_DIB_HEADER_SIZES = (12, 40, 52, 56, 64, 108, 124)


def is_bmp(data: bytes) -> bool:
    return data[:2] == BMP_HEADER and struct.unpack_from("<I", data, 14)[0] in BMP_DIB_HEADER_SIZES


ICO_HEADER = b"\0\0\1\0"


def is_ico(data: bytes) -> bool:
    # followed by the number of images, which cannot be zero:
    return data[:4] == ICO_HEADER and struct.unpack_from("<H", data, 4)[0] > 0


def is_ppm(data: bytes) -> bool:
    # "P1" to "P6", followed by whitespace:
    return data[:1] == b"P" and data[1:2] in (b"1", b"2", b"3", b"4", b"5", b"6") and data[2:3] in (b" ", b"\t", b"\n", b"\r", b"\v", b"\f")


def ico_has_apng(data: SizedBuffer) -> bool:
    # each 16-byte directory entry after the 6-byte header has the offset of its image,
    # which Pillow parses as a PNG file if it starts with the PNG signature:
    view = memoryview(data)
    count = struct.unpack_from("<H", view, 4)[0]
    for i in range(count):
        entry = 6 + i * 16
        if entry + 16 > len(view):
            break
        offset = struct.unpack_from("<I", view, entry + 12)[0]
        if view[offset:offset + len(PNG_HEADER)] == PNG_HEADER and is_apng(view[offset:]):
            return True
    return False


HEADERS: dict[Callable[[bytes], bool], str] = {
    is_png: "png",
    is_webp: "webp",
    is_jpeg: "jpeg",
    is_svg: "svg",
    is_xpm: "xpm",
    is_tiff: "tiff",
    is_bmp: "bmp",
    is_ico: "ico",
    is_ppm: "ppm",
}


def get_image_type(data: SizedBuffer) -> str:
    if not data:
        return ""
    if len(data) < 32:
        return ""
    header = memoryview_to_bytes(data[:HEADER_SIZE])
    for fn, encoding in HEADERS.items():
        if fn(header):
            # APNG must be allowed explicitly, even when embedded in an ICO file,
            # Pillow parses the animation chunks in `Image.open()` - see CVE-2026-112399:
            if (encoding == "png" and is_apng(data)) or (encoding == "ico" and ico_has_apng(data)):
                return "apng"
            return encoding
    return ""
