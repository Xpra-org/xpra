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


def is_png(data: bytes) -> bool:
    return data.startswith(PNG_HEADER)


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
    return data[:5] == b"<?xml" or data[:4] == b"<svg"


XPM_HEADER = b"/* XPM */"


def is_xpm(data: bytes) -> bool:
    return data[:9] == XPM_HEADER


def is_tiff(data: bytes) -> bool:
    if data[:2] == b"II":
        return data[2] == 42 and data[3] == 0
    if data[:2] == b"MM":
        return data[2] == 0 and data[3] == 42
    return False


HEADERS: dict[Callable[[bytes], bool], str] = {
    is_png: "png",
    is_webp: "webp",
    is_jpeg: "jpeg",
    is_svg: "svg",
    is_xpm: "xpm",
    is_tiff: "tiff",
}


def get_image_type(data: SizedBuffer) -> str:
    if not data:
        return ""
    if len(data) < 32:
        return ""
    header = memoryview_to_bytes(data[:32])
    for fn, encoding in HEADERS.items():
        if fn(header):
            return encoding
    return ""
