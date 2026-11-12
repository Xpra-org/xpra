# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Parsing and validation of the `window-draw` packets (and of `window-draw-fragment`, which shares their layout),
the server is not trusted: everything is bounded before it reaches the decoders.
The position of the update is not validated here:
the window may have been resized since the server sent it.
"""

from collections.abc import Sequence
from typing import NamedTuple

from xpra.common import SizedBuffer
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.net.packet_values import check_key, check_value, get_int_tuples, get_mmap_chunks
from xpra.codecs.constants import RGB_FORMAT_BPP, check_image_size, check_rgb_buffer
from xpra.util.env import envint
from xpra.util.str_fn import repr_ellipsized
from xpra.log import Logger

log = Logger("window", "draw")

# limits for the `window-draw` and `window-draw-fragment` packets:
MAX_DRAW_PIXELS: int = envint("XPRA_MAX_DRAW_PIXELS", 8192 * 8192)
MAX_DRAW_OPTIONS: int = envint("XPRA_MAX_DRAW_OPTIONS", 64)
MAX_MMAP_CHUNKS: int = envint("XPRA_MAX_MMAP_CHUNKS", 256)
MAX_SCROLL_RECTS: int = envint("XPRA_MAX_SCROLL_RECTS", 4096)
MAX_DRAW_FRAGMENTS: int = envint("XPRA_MAX_DRAW_FRAGMENTS", 256)
MAX_FRAGMENT_SIZE: int = 65536
# compressed pixel data is never this much bigger than the pixels it encodes:
MAX_BYTES_PER_PIXEL: int = 8
DATA_SLACK: int = 65536

# encodings that may not have any pixel data:
NO_DATA_ENCODINGS: Sequence[str] = ("mmap", "scroll", "void")
RGB_ENCODINGS: dict[str, str] = {"rgb24": "RGB", "rgb32": "RGBX"}
SIGNATURES: dict[str, bytes] = {
    "jpeg": b"\xff\xd8\xff",
    "jpega": b"\xff\xd8\xff",
    "png": b"\x89PNG\r\n\x1a\n",
    "png/P": b"\x89PNG\r\n\x1a\n",
    "png/L": b"\x89PNG\r\n\x1a\n",
    "webp": b"RIFF",
}
# options that only the client sets, the server must not send them:
CLIENT_OPTIONS: Sequence[str] = ("fragments", "missing-fragments", "encoding", "stream", "pbo")


class DrawRequest(NamedTuple):
    """ the fields of a `window-draw` packet """
    wid: int
    x: int
    y: int
    width: int
    height: int
    coding: str
    data: SizedBuffer
    sequence: int
    rowstride: int
    options: dict


def get_size_option(options: dict, key: str) -> tuple[int, int]:
    value = options[key]
    if not isinstance(value, (tuple, list)) or len(value) != 2 or any(type(v) is not int for v in value):
        raise ValueError(f"invalid draw option {key!r}: {value!r}")
    width, height = value
    check_image_size(width, height, key)
    return width, height


def validate_draw_options(options: dict) -> dict:
    """
    returns a copy of the options received from the server,
    with the options we validate specifically normalized to tuples,
    raises `ValueError` or `TypeError` if they are not acceptable
    """
    validated = {}
    for key, value in options.items():
        check_key(key, "draw option")
        if key in CLIENT_OPTIONS:
            log("ignoring client-only draw option %r=%s", key, repr_ellipsized(value))
            continue
        if key == "chunks":
            value = get_mmap_chunks(value, MAX_MMAP_CHUNKS, "draw option")
        elif key == "scroll":
            value = get_int_tuples(value, key, 6, MAX_SCROLL_RECTS, 2**16, "draw option")
            if any(w <= 0 or h <= 0 for _x, _y, w, h, _dx, _dy in value):
                raise ValueError("invalid scroll rectangle size")
        elif key in ("scaled_size", "window-size"):
            value = get_size_option(options, key)
        else:
            check_value(key, value, "draw option")
        validated[key] = value
    return validated


def parse_draw_packet(packet: Packet, size: int = 11) -> DrawRequest:
    """
    parse the fields of a `window-draw` packet,
    or of the `window-draw-fragment` packets which use the same layout, but with extra fields.
    raises `ValueError` or `TypeError` if the packet is malformed
    """
    packet.check_len(size, size)
    wid = packet.get_wid()
    x = packet.get_i16(2)
    y = packet.get_i16(3)
    width = packet.get_u16(4)
    height = packet.get_u16(5)
    coding = packet.get_str(6, 32)
    if BACKWARDS_COMPATIBLE and coding in ("mmap", "scroll") and not isinstance(packet[7], (bytes, bytearray, memoryview)):
        # v7 servers running in backwards compatible mode also send the `chunks` / `scroll` options here,
        # we only use the options:
        data = b""
    else:
        data = packet.get_buffer(7)
    sequence = packet.get_u64(8)
    rowstride = packet.get_u32(9)
    options = validate_draw_options(packet.get_dict(10, MAX_DRAW_OPTIONS))
    return DrawRequest(wid, x, y, width, height, coding, data, sequence, rowstride, options)


def check_draw_request(request: DrawRequest) -> str:
    """
    verify that the pixel data is consistent with the frame's geometry and encoding,
    returns an error message if it is not
    """
    coding = request.coding
    width, height = request.width, request.height
    options = request.options
    data_size = len(request.data)
    if coding in ("scroll", "void"):
        if coding == "scroll" and "scroll" not in options:
            return "scroll packet without any scroll rectangles"
        return ""
    if width <= 0 or height <= 0:
        return f"invalid {coding} update size {width}x{height}"
    if width * height > MAX_DRAW_PIXELS:
        return f"{coding} update {width}x{height} exceeds the {MAX_DRAW_PIXELS} pixels limit"
    # the pixel data may encode a scaled down version of the update:
    enc_width, enc_height = options.get("scaled_size", (width, height))
    if enc_width * enc_height > MAX_DRAW_PIXELS:
        return f"{coding} update scaled size {enc_width}x{enc_height} exceeds the {MAX_DRAW_PIXELS} pixels limit"
    try:
        if coding == "mmap":
            if data_size:
                return f"mmap packet with {data_size} bytes of pixel data"
            chunks = options.get("chunks")
            if not chunks:
                return "mmap packet without any chunks"
            mmap_size = sum(length for _offset, length in chunks)
            rgb_format = options.get("rgb_format", "RGB")
            check_rgb_buffer(rgb_format, mmap_size, enc_width, enc_height, request.rowstride or enc_width * RGB_FORMAT_BPP.get(rgb_format, 4), "mmap")
            return ""
        if coding in RGB_ENCODINGS:
            rgb_format = options.get("rgb_format") or RGB_ENCODINGS[coding]
            bpp = RGB_FORMAT_BPP.get(rgb_format, 0)
            if not bpp:
                return f"unknown {coding} pixel format {rgb_format!r}"
            rowstride = request.rowstride or width * bpp
            if any(options.get(x) for x in ("lz4", "zstd")):
                # the decompressed pixels are checked by the backing:
                raw_size = rowstride * height
                if not 0 < data_size <= raw_size + raw_size // 255 + DATA_SLACK:
                    return f"invalid {coding} compressed data size: {data_size} bytes for {raw_size} bytes of pixels"
                return ""
            check_rgb_buffer(rgb_format, data_size, width, height, rowstride, coding)
            return ""
    except ValueError as e:
        return str(e)
    if data_size <= 0:
        return f"no {coding} pixel data"
    max_size = enc_width * enc_height * MAX_BYTES_PER_PIXEL + DATA_SLACK
    if data_size > max_size:
        return f"too much {coding} data: {data_size} bytes for {enc_width}x{enc_height} pixels"
    signature = SIGNATURES.get(coding, b"")
    if signature and bytes(memoryview(request.data)[:len(signature)]) != signature:
        return f"invalid {coding} data signature"
    return ""
