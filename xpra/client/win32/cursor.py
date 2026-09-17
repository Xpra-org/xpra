# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import sizeof, byref, cast, c_void_p, memmove, create_string_buffer, POINTER
from collections.abc import Sequence, Iterable

import win32con

from xpra.util.str_fn import memoryview_to_bytes
from xpra.platform.gui import get_default_cursor_size
from xpra.platform.win32.common import (
    GetDC, ReleaseDC, BITMAPV5HEADER, CreateDIBSection, CreateBitmap, DeleteObject,
    ICONINFO, CreateIconIndirect, DestroyCursor,
)
from xpra.log import Logger

log = Logger("client", "cursor")


def scale_cursor(w: int, h: int, xhot: int, yhot: int, pixels: bytes,
                 xscale: float, yscale: float) -> tuple[int, int, int, int, bytes]:
    sw = max(1, round(w * xscale))
    sh = max(1, round(h * yscale))
    if (sw, sh) == (w, h):
        return w, h, xhot, yhot, pixels
    try:
        from PIL import Image
    except ImportError:
        log("cannot scale the cursor without pillow")
        return w, h, xhot, yhot, pixels
    img = Image.frombytes("RGBA", (w, h), pixels, "raw", "RGBA", w * 4, 1)
    pixels = img.resize((sw, sh), Image.Resampling.BILINEAR).tobytes("raw", "RGBA")
    return sw, sh, round(xhot * xscale), round(yhot * yscale), pixels


def pad_cursor(w: int, h: int, pixels: bytes, min_width: int, min_height: int) -> tuple[int, int, bytes]:
    """
    Paste the cursor in the top-left corner of a transparent image of at least this size,
    so the hotspot does not move.
    """
    pw, ph = max(w, min_width), max(h, min_height)
    if (pw, ph) == (w, h):
        return w, h, pixels
    stride = w * 4
    padding = bytes((pw - w) * 4)
    rows = b"".join(pixels[y * stride:(y + 1) * stride] + padding for y in range(h))
    return pw, ph, rows + bytes((ph - h) * pw * 4)


def make_hcursor(w: int, h: int, xhot: int, yhot: int, pixels: bytes) -> int:
    """
    Create a native cursor from `RGBA` pixels,
    Windows shows it at this exact size.
    """
    header = BITMAPV5HEADER()
    header.bV5Size = sizeof(BITMAPV5HEADER)
    header.bV5Width = w
    # negative height for a top-down bitmap, like the pixels we get:
    header.bV5Height = -h
    header.bV5Planes = 1
    header.bV5BitCount = 32
    header.bV5Compression = win32con.BI_BITFIELDS
    header.bV5RedMask = 0x00FF0000
    header.bV5GreenMask = 0x0000FF00
    header.bV5BlueMask = 0x000000FF
    header.bV5AlphaMask = 0xFF000000
    bits = c_void_p()
    hdc = GetDC(0)
    try:
        color = CreateDIBSection(hdc, byref(header), win32con.DIB_RGB_COLORS, byref(bits), None, 0)
    finally:
        ReleaseDC(0, hdc)
    if not color:
        log.error("Error: failed to create a %ix%i cursor bitmap", w, h)
        return 0
    mask = 0
    try:
        size = w * h * 4
        bgra = bytearray(pixels[:size])
        bgra[0::4] = pixels[2:size:4]
        bgra[2::4] = pixels[0:size:4]
        # Windows ignores the mask of a cursor that has an alpha channel,
        # but a cursor with no opaque pixel at all is treated as having none:
        # use a transparent mask for that one, or it would paint a black square
        transparent = not any(bgra[3::4])
        if transparent:
            bgra = bytearray(size)
        memmove(bits, bytes(bgra), size)
        # the rows of a monochrome bitmap are word aligned:
        mask_row = ((w + 15) // 16) * 2
        mask_bits = create_string_buffer(b"\xff" * (mask_row * h) if transparent else b"", mask_row * h)
        mask = CreateBitmap(w, h, 1, 1, cast(mask_bits, POINTER(c_void_p)))
        if not mask:
            log.error("Error: failed to create a %ix%i cursor mask", w, h)
            return 0
        info = ICONINFO()
        info.fIcon = False
        info.xHotspot = max(0, min(xhot, w - 1))
        info.yHotspot = max(0, min(yhot, h - 1))
        info.hbmMask = mask
        info.hbmColor = color
        # the cursor gets its own copy of the bitmaps:
        return CreateIconIndirect(byref(info)) or 0
    finally:
        DeleteObject(color)
        if mask:
            DeleteObject(mask)


class Win32Cursors:
    """
    The native cursors created from the server's cursor data,
    windows showing the same cursor share the same `HCURSOR`.
    """

    def __init__(self):
        self.hcursors: dict[tuple, int] = {}

    def get_hcursor(self, cursor_data: Sequence, xscale=1.0, yscale=1.0) -> int:
        if len(cursor_data) < 9:
            log.warn("Warning: invalid cursor data")
            return 0
        encoding, _, _, w, h, xhot, yhot, serial, pixels = cursor_data[:9]
        if encoding != "raw":
            log.warn("Warning: invalid cursor encoding: %s", encoding)
            return 0
        pixels = memoryview_to_bytes(pixels)
        if w <= 0 or h <= 0 or len(pixels) < w * h * 4:
            log.warn("Warning: invalid %ix%i cursor with %i bytes of pixel data", w, h, len(pixels))
            return 0
        # pixels of the previous cursor can remain visible outside of a smaller one (seen with VirtualBox),
        # so we make them at least as big as the system cursors:
        min_size = get_default_cursor_size()
        key = (w, h, xhot, yhot, pixels, xscale, yscale, min_size)
        hcursor = self.hcursors.get(key, 0)
        if not hcursor:
            sw, sh, sx, sy, spixels = scale_cursor(w, h, xhot, yhot, pixels, xscale, yscale)
            pw, ph, spixels = pad_cursor(sw, sh, spixels, *min_size)
            hcursor = make_hcursor(pw, ph, sx, sy, spixels)
            log("make_hcursor for %ix%i cursor with serial=%#x, scaled to %ix%i, padded to %ix%i: %#x",
                w, h, serial, sw, sh, pw, ph, hcursor)
            if hcursor:
                self.hcursors[key] = hcursor
        return hcursor

    def free_unused(self, in_use: Iterable[int]) -> None:
        in_use = set(in_use)
        for key, hcursor in tuple(self.hcursors.items()):
            if hcursor not in in_use:
                del self.hcursors[key]
                log("DestroyCursor(%#x)", hcursor)
                DestroyCursor(hcursor)

    def cleanup(self) -> None:
        self.free_unused(())
