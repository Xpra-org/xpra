#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from ctypes import c_void_p, byref, addressof, sizeof, WinError, get_last_error, memmove
from ctypes.wintypes import HBITMAP, HDC, HWND
from collections.abc import Sequence, Callable

from xpra.platform.win32.common import (
    SelectObject, DeleteObject,
    DeleteDC,  # ReleaseDC
    CreateCompatibleDC,
    BITMAPV5HEADER, CreateDIBSection,
    BitBlt,
)
from xpra.client.gui.window.backing import WindowBackingBase, fire_paint_callbacks
from xpra.common import PaintCallbacks
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("draw")


class GDIBacking(WindowBackingBase):

    RGB_MODES = ("BGRX", )

    def __init__(self, wid: int, hdc: HDC, hwnd: HWND, width: int, height: int, alpha: bool):
        super().__init__(wid, alpha)
        self.hdc = hdc
        self.hwnd = hwnd
        self.width = width
        self.height = height
        self.pixels = c_void_p()
        self.bitmap = self.create_bitmap(width, height)
        # the superclass requires this attribute to be set to enable rendering:
        self._backing = True
        SelectObject(hdc, self.bitmap)

    def get_rgb_formats(self) -> Sequence[str]:
        if self._alpha_enabled:
            return ("BGRA", )
        return ("BGRX", )

    def create_bitmap(self, width, height) -> HBITMAP:
        header = BITMAPV5HEADER()
        header.bV5Size = sizeof(BITMAPV5HEADER)
        header.bV5Width = width
        header.bV5Height = -height
        header.bV5Planes = 1
        header.bV5BitCount = 32
        if self._alpha_enabled:
            header.bV5Compression = win32con.BI_BITFIELDS
            header.bV5RedMask = 0x00FF0000  # Red in byte 2
            header.bV5GreenMask = 0x0000FF00  # Green in byte 1
            header.bV5BlueMask = 0x000000FF  # Blue in byte 0
            header.bV5AlphaMask = 0xFF000000  # ← Alpha in byte 3 (non-zero!)
        else:
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
        new_bitmap = self.create_bitmap(width, height)
        SelectObject(self.hdc, new_bitmap)

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

    def paint(self, hdc: HDC) -> None:
        if self.bitmap:
            BitBlt(hdc, 0, 0, self.width, self.height, self.hdc, 0, 0, win32con.SRCCOPY)

    def with_gfx_context(self, function: Callable, *args) -> None:
        # the do_paint_rgb function access the pixel buffer directly
        # so we don't need to use the main thread:
        log("with_gfx_context: %s", function)
        function(None, *args)

    def do_paint_rgb(self, context, encoding: str, rgb_format: str, img_data,
                     x: int, y: int, width: int, height: int, render_width: int, render_height: int, rowstride: int,
                     options: typedict, callbacks: PaintCallbacks) -> None:
        log("do_paint_rgb%s", (context, encoding, rgb_format, type(img_data),
                               x, y, width, height, render_width, render_height, rowstride,
                               options, callbacks))
        if not self.bitmap:
            fire_paint_callbacks(callbacks, False, "window has already been destroyed")
            return

        if len(rgb_format) != 4:
            if rgb_format == "RGB":
                from xpra.codecs.argb.argb import rgb_to_bgrx
                img_data = rgb_to_bgrx(img_data)
                rowstride = width * 4
            else:
                log.error("Error: paint must convert from %s to BGRX", rgb_format)
                fire_paint_callbacks(callbacks, False, "pixel format conversion needed")
                return

        bitmap_stride = self.width * 4
        offset = y * bitmap_stride + x * 4
        src = addressof(c_void_p.from_buffer(img_data))
        dst = c_void_p(self.pixels.value + offset)
        log(f"draw_region {offset=} {src=} - {dst=} {bitmap_stride=} {rowstride=}")
        if rowstride == bitmap_stride and x == 0 and y >= 0 and width == self.width and y + height <= self.height:
            # happy path: copy all at once
            memmove(dst, src, rowstride * height)
        else:
            # slow path: copy each row separately
            rowlen = min(width, self.width - x) * 4
            for i in range(min(height, self.height - y)):
                dst = c_void_p(self.pixels.value + offset + i * bitmap_stride)
                src = addressof(c_void_p.from_buffer(img_data)) + i * rowstride
                memmove(dst, src, rowlen)
        fire_paint_callbacks(callbacks)

    def close(self) -> None:
        bitmap = self.bitmap
        if bitmap:
            self.bitmap = 0
            DeleteObject(bitmap)
        super().close()
