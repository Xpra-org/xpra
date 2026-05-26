# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from typing import Any
from collections.abc import Sequence

from xpra.net.rfb.const import RFBEncoding
from xpra.codecs.image import ImageWrapper
from xpra.codecs.pillow.encoder import encode
from xpra.util.objects import typedict
from xpra.util.str_fn import hexstr
from xpra.log import Logger

log = Logger("rfb")

PILLOW_OPTIONS = typedict({"alpha": False})


def pillow_encode(encoding: str, img: ImageWrapper, quality: int = 0, speed: int = 0) -> bytes:
    options = typedict(PILLOW_OPTIONS)
    if quality > 0:
        options["quality"] = min(100, max(0, int(quality)))
    if speed > 0:
        options["speed"] = min(100, max(0, int(speed)))
    return encode(encoding, img, options)[1].data


def make_header(encoding: int, x: int, y: int, w: int, h: int) -> bytes:
    fbupdate = struct.pack(b"!BBH", 0, 0, 1)
    rect = struct.pack(b"!HHHHi", x, y, w, h, encoding)
    return fbupdate + rect


def rgb222_encode(window: Any, x: int, y: int, w: int, h: int) -> Sequence[bytes]:
    img = window.get_image(x, y, w, h)
    window.acknowledge_changes()
    return rgb222_encode_image(img, x, y, w, h)


def rgb222_encode_image(img: ImageWrapper, x: int, y: int, w: int, h: int) -> Sequence[bytes]:
    header = make_header(RFBEncoding.RAW, x, y, w, h)
    if img.get_pixel_format() != "BGRX":
        log.warn("Warning: cannot convert %s to rgb222", img.get_pixel_format())
        return []
    pixels = img.get_pixels()
    from xpra.codecs.argb.argb import bgra_to_rgb222  # pylint: disable=no-name-in-module
    data = bgra_to_rgb222(pixels)
    return header, data


def raw_encode(window: Any, x: int, y: int, w: int, h: int) -> Sequence[bytes]:
    img = window.get_image(x, y, w, h)
    window.acknowledge_changes()
    return raw_encode_image(img, x, y, w, h)


def raw_encode_image(img: ImageWrapper, x: int, y: int, w: int, h: int) -> Sequence[bytes]:
    header = make_header(RFBEncoding.RAW, x, y, w, h)
    return header, raw_pixels(img)


def raw_pixels(img: ImageWrapper | None) -> bytes:
    if not img:
        return b""
    w = img.get_width()
    h = img.get_height()
    Bpp = len(img.get_pixel_format())  # ie: BGRX -> 4
    if img.get_rowstride() != w * Bpp:
        img.restride(w * Bpp)
    pixels = img.get_pixels()
    assert len(pixels) >= Bpp * w * h, "expected %i pixels for %ix%i-%i but got %i" % (
        Bpp * w * h, w, h, Bpp, len(pixels))
    return pixels[:Bpp * w * h]


def zlib_encode(window: Any, x: int, y: int, w: int, h: int, compressor: Any = None) -> Sequence[bytes]:
    img = window.get_image(x, y, w, h)
    window.acknowledge_changes()
    return zlib_encode_image(img, x, y, w, h, compressor)


def zlib_encode_image(img: ImageWrapper, x: int, y: int, w: int, h: int, compressor: Any = None) -> Sequence[bytes]:
    if not img:
        return []
    pixels = raw_pixels(img)
    import zlib  # pylint: disable=import-outside-toplevel
    if isinstance(pixels, memoryview):
        pixels = pixels.tobytes()
    # the RFB Zlib pseudo-encoding requires a single zlib stream maintained
    # across all rectangles of a connection - the caller is expected to pass
    # in a persistent compressor and we flush with Z_SYNC_FLUSH so the stream
    # stays open for subsequent rectangles.
    if compressor is None:
        compressor = zlib.compressobj(1)
    data = compressor.compress(pixels) + compressor.flush(zlib.Z_SYNC_FLUSH)
    log("zlib compressed %i down to %i", len(pixels), len(data))
    header = make_header(RFBEncoding.ZLIB, x, y, w, h) + struct.pack(b"!I", len(data))
    return header, data


def tight_encode(window: Any, x: int, y: int, w: int, h: int, quality: int = 0, speed: int = 0) -> Sequence[bytes]:
    img = window.get_image(x, y, w, h)
    window.acknowledge_changes()
    return tight_encode_image(img, x, y, w, h, quality, speed)


def tight_encode_image(img: ImageWrapper, x: int, y: int, w: int, h: int,
                       quality: int = 0, speed: int = 0) -> Sequence[bytes]:
    if not img:
        return []
    data = pillow_encode("jpeg", img, quality, speed)
    header = tight_header(RFBEncoding.TIGHT, x, y, w, h, 0x90, len(data))
    return header, data


def tight_header(encoding: int, x: int, y: int, w: int, h: int, control: int, length: int) -> bytes:
    header = make_header(encoding, x, y, w, h)
    header += struct.pack(b"!B", control)
    # the length header is in a weird format:
    if length < 128:
        header += struct.pack(b"!B", length)
    elif length < 16383:
        header += struct.pack(b"!BB", 0x80 + (length & 0x7F), length >> 7)
    else:
        assert length < 4194303
        header += struct.pack(b"!BBB", 0x80 + (length & 0x7F), 0x80 + ((length >> 7) & 0x7F), length >> 14)
    log("tight header for %i bytes %s", length, hexstr(header))
    return header


def tight_png(window: Any, x: int, y: int, w: int, h: int, speed: int = 0) -> Sequence[bytes]:
    img = window.get_image(x, y, w, h)
    window.acknowledge_changes()
    return tight_png_image(img, x, y, w, h, speed)


def tight_png_image(img: ImageWrapper, x: int, y: int, w: int, h: int, speed: int = 0) -> Sequence[bytes]:
    if not img:
        return []
    data = pillow_encode("png", img, speed=speed)
    header = tight_header(RFBEncoding.TIGHT_PNG, x, y, w, h, 0x80 + 0x20, len(data))
    return header, data
