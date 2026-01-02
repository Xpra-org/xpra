#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from io import BytesIO
from ctypes import c_void_p, byref, sizeof, WinError, get_last_error, memmove
from ctypes.wintypes import HBITMAP, HDC, HWND
from collections.abc import MutableSequence, Callable

from xpra.platform.win32.common import (
    SelectObject, DeleteObject,
    GetDC, ReleaseDC, DeleteDC,  # ReleaseDC
    CreateCompatibleDC,
    BITMAPV5HEADER, CreateDIBSection,
    InvalidateRect, SetDIBits,
    BeginPaint, EndPaint, PAINTSTRUCT, BitBlt,
)
from xpra.client.gui.window.backing import fire_paint_callbacks
from xpra.util.objects import typedict
from xpra.util.str_fn import memoryview_to_bytes
from xpra.common import roundup
from xpra.log import Logger

log = Logger("draw")


class GDIBacking:

    def __init__(self, hdc: HDC, hwnd: HWND, width: int, height: int, alpha: bool):
        self.hdc = hdc
        self.hwnd = hwnd
        self.width = width
        self.height = height
        self.alpha = alpha
        self.pixels = c_void_p()
        self.bitmap = self.create_bitmap()
        SelectObject(hdc, self.bitmap)

    def create_bitmap(self) -> HBITMAP:
        header = BITMAPV5HEADER()
        header.bV5Size = sizeof(BITMAPV5HEADER)
        header.bV5Width = self.width
        header.bV5Height = -self.height
        header.bV5Planes = 1
        header.bV5BitCount = 8 * (3 + int(self.alpha))
        header.bV5Compression = win32con.BI_RGB
        bitmap = CreateDIBSection(self.hdc, byref(header), win32con.DIB_RGB_COLORS, byref(self.pixels), None, 0)
        if not self.pixels or not bitmap:
            log.error("Error creating bitmap backing of size %ix%i", self.width, self.height)
            raise WinError(get_last_error())
        return bitmap

    def resize(self, width: int, height: int):
        bitmap = self.bitmap
        if not bitmap:
            raise RuntimeError("GDI backing has already been freed")
        new_bitmap = self.create_bitmap()

        # copy old bitmap contents
        temp_dc = CreateCompatibleDC(None)
        SelectObject(temp_dc, bitmap)

        # rect = RECT(0, 0, width, height)
        # FillRect(self.hdc, byref(rect), GetStockObject(BLACK_BRUSH))

        # Copy overlapping region
        copy_width = min(width, self.width)
        copy_height = min(height, self.height)

        BitBlt(self.hdc, 0, 0, copy_width, copy_height, temp_dc, 0, 0, win32con.SRCCOPY)

        DeleteDC(temp_dc)
        DeleteObject(bitmap)

        self.bitmap = new_bitmap
        self.width = width
        self.height = height

    def eos(self):
        pass

    def redraw(self):
        if self.hwnd:
            InvalidateRect(self.hwnd, None, True)

    def paint(self) -> None:
        ps = PAINTSTRUCT()
        hdc = BeginPaint(self.hwnd, byref(ps))
        log("paint hdc=%#x", hdc)
        try:
            if self.bitmap:
                BitBlt(hdc, 0, 0, self.width, self.height, self.hdc, 0, 0, win32con.SRCCOPY)
        finally:
            EndPaint(self.hwnd, byref(ps))

    def draw_region(self, x: int, y: int, width: int, height: int,
                    coding: str, img_data, rowstride: int,
                    options: typedict, callbacks: MutableSequence[Callable]):
        log("draw_region%s", (x, y, width, height, coding, type(img_data), rowstride, options, callbacks))
        if not self.bitmap:
            fire_paint_callbacks(callbacks, False, "window has already been destroyed")
            return

        def done() -> None:
            if options.intget("flush", 0) == 0:
                self.redraw()
            fire_paint_callbacks(callbacks)

        def err(msg: str) -> None:
            fire_paint_callbacks(callbacks, False, msg)

        if options.boolget("lz4"):
            from xpra.net.lz4.lz4 import decompress
            img_data = decompress(img_data)
            log("lz4 decompressed: %r (%s)", img_data, type(img_data))
            img_data = memoryview_to_bytes(img_data)
        bitmap_bpp = 3 + int(self.alpha)
        bitmap_stride = roundup(self.width * bitmap_bpp, 4)
        if coding in ("rgb24", "rgb32"):
            if (coding == "rgb32" and not self.alpha) or (coding == "rgb24" and self.alpha):
                # mismatch between RGB format received and the HBITMAP buffer format
                # so use a temporary Bitmap and BitBlt:
                if rowstride == 0 or rowstride % 4 != 0:
                    err("invalid rowstride %i" % rowstride)
                    return

                hdc = GetDC(None)
                hdc_src = CreateCompatibleDC(hdc)
                hdc_dst = CreateCompatibleDC(hdc)

                rgb = BITMAPV5HEADER()
                rgb.bV5Size = sizeof(BITMAPV5HEADER)
                rgb.bV5Width = rowstride // (4 if coding == "rgb32" else 3)
                rgb.bV5Height = -height
                rgb.bV5Planes = 1
                rgb.bV5BitCount = 32 if coding == "rgb32" else 24
                rgb.bV5Compression = win32con.BI_RGB
                log("converting from %i bits to alpha=%s", rgb.bV5BitCount, self.alpha)

                # use a temporary bitmap:
                bitmap = CreateDIBSection(hdc, byref(rgb), win32con.DIB_RGB_COLORS, byref(c_void_p()), None, 0)
                SetDIBits(hdc, bitmap, 0, height, img_data, byref(rgb), win32con.DIB_RGB_COLORS)
                old_src = SelectObject(hdc_src, bitmap)
                old_dst = SelectObject(hdc_dst, self.bitmap)
                try:
                    # Blit the rectangle to target
                    BitBlt(hdc_dst, x, y, width, height, hdc_src, 0, 0, win32con.SRCCOPY)
                finally:
                    SelectObject(hdc_src, old_src)
                    SelectObject(hdc_dst, old_dst)
                    DeleteObject(bitmap)
                    DeleteDC(hdc_src)
                    DeleteDC(hdc_dst)
                    ReleaseDC(None, hdc)
                done()
                return
            pixels = img_data
        elif coding in ("png", "jpeg", "webp"):
            from PIL import Image
            img = Image.open(BytesIO(img_data))
            mode = "RGBA" if self.alpha else "RGB"
            output_mode = "BGRA" if self.alpha else "BGR"
            if img.mode != mode:
                img = img.convert(mode)
            pixels = img.tobytes("raw", output_mode)
            rowstride = len(output_mode) * img.size[0]
        else:
            err(f"unsupported format {coding!r}")
            return

        offset = y * bitmap_stride + x * bitmap_bpp
        dst = c_void_p(self.pixels.value + offset)
        log(f"draw_region {offset=} {dst=} {bitmap_bpp=} {bitmap_stride=} {rowstride=}")
        if rowstride == bitmap_stride and x == 0 and y >= 0 and width == self.width and y + height <= self.height:
            # happy path: copy all at once
            memmove(dst, pixels, rowstride * height)
        else:
            # slow path: copy each row separately
            rowlen = min(width, self.width - x) * bitmap_bpp
            for i in range(min(height, self.height - y)):
                dst = c_void_p(self.pixels.value + offset + i * bitmap_stride)
                memmove(dst, pixels[i * rowstride:], rowlen)
        done()

    def cleanup(self) -> None:
        bitmap = self.bitmap
        if bitmap:
            self.bitmap = 0
            DeleteObject(bitmap)
