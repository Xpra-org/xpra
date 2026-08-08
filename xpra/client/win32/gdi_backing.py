#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from ctypes import (
    c_void_p, byref, addressof, sizeof, WinError, get_last_error, memmove, create_string_buffer,
)
from ctypes.wintypes import HBITMAP, HDC, HWND
from collections.abc import Callable

from xpra.platform.win32.common import (
    SelectObject, DeleteObject,
    DeleteDC,  # ReleaseDC
    CreateCompatibleDC,
    BITMAPV5HEADER, CreateDIBSection,
    BitBlt, StretchBlt, SetStretchBltMode,
)
from xpra.client.gui.window.backing import WindowBackingBase, fire_paint_callbacks, PaintCallbacks, clip_span
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("draw")


class GDIBacking(WindowBackingBase):

    # the DIB section is always 32-bit, so both formats are painted the same way:
    # `BGRA` is only offered when the window is transparent
    # (see `get_rgb_formats` in the superclass)
    RGB_MODES = ("BGRA", "BGRX")

    def __init__(self, wid: int, hdc: HDC, hwnd: HWND, width: int, height: int, alpha: bool):
        super().__init__(wid, alpha)
        self.hdc = hdc
        self.hwnd = hwnd
        self.size = (width, height)
        self.render_size = (width, height)
        self.pixels = c_void_p()
        self.bitmap = self.create_bitmap(width, height)
        # the superclass requires this attribute to be set to enable rendering:
        self._backing = True
        SelectObject(hdc, self.bitmap)

    def bitmap_header(self, width: int, height: int) -> BITMAPV5HEADER:
        """
        Describe the DIB section to GDI.
        The `BGRX` case must declare *no* alpha channel: the `X` byte of the pixels
        the server sends us is padding, and its value is undefined.
        Some producers do fill it in - `rgb_to_bgrx` writes `0xff`,
        so does libyuv's `*ToARGB` family - but nothing guarantees it:
        an X11 depth-24 capture ships whatever the pad bits happened to hold,
        and `TJPF_BGRX` is documented as leaving the `X` component undefined.
        Declaring an alpha mask over it would let GDI - and DWM - interpret that padding.
        """
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
            # 32-bit `BI_RGB` is the "top byte unused" format:
            # GDI copies it but never interprets it, which is exactly what `BGRX` needs
            header.bV5Compression = win32con.BI_RGB
            header.bV5AlphaMask = 0  # (already the default, spelled out: `X` is not alpha)
        return header

    def create_bitmap(self, width, height) -> HBITMAP:
        header = self.bitmap_header(width, height)
        bitmap = CreateDIBSection(self.hdc, byref(header), win32con.DIB_RGB_COLORS, byref(self.pixels), None, 0)
        if not self.pixels or not bitmap:
            log.error("Error creating bitmap backing of size %ix%i", width, height)
            raise WinError(get_last_error())
        return bitmap

    def init(self, ww: int, wh: int, bw: int, bh: int) -> None:
        """
        `(ww, wh)` is the on-screen (client, desktop-scaled) size,
        `(bw, bh)` is the backing buffer (server pixel) size:
        only the latter requires reallocating the DIB section.
        """
        self.render_size = (ww, wh)
        if (bw, bh) != self.size:
            self._resize_backing(bw, bh)

    def _resize_backing(self, width: int, height: int) -> None:
        bitmap = self.bitmap
        if not bitmap:
            raise RuntimeError("GDI backing has already been freed")
        new_bitmap = self.create_bitmap(width, height)
        SelectObject(self.hdc, new_bitmap)

        # copy old bitmap contents
        temp_dc = CreateCompatibleDC(None)
        SelectObject(temp_dc, bitmap)

        # Copy overlapping region
        old_width, old_height = self.size
        copy_width = min(width, old_width)
        copy_height = min(height, old_height)

        BitBlt(self.hdc, 0, 0, copy_width, copy_height, temp_dc, 0, 0, win32con.SRCCOPY)

        DeleteDC(temp_dc)
        DeleteObject(bitmap)

        self.bitmap = new_bitmap
        self.size = (width, height)

    def paint(self, hdc: HDC) -> None:
        """
        Blit the backing into the DC `WM_PAINT` gave us.
        Neither raster operation below specifies what happens to the top byte,
        but it does not matter: the destination is an ordinary window DC,
        and nothing reads the top byte of one of those.
        The calls that *do* consume it - `AlphaBlend` with `AC_SRC_ALPHA`,
        `UpdateLayeredWindow` with `ULW_ALPHA` -
        must only ever be used with an alpha-enabled backing.
        (`TransparentBlt` is not one of them: it colour-keys on an RGB value.)
        """
        if not self.bitmap:
            return
        bw, bh = self.size
        rw, rh = self.render_size
        if (bw, bh) == (rw, rh):
            BitBlt(hdc, 0, 0, bw, bh, self.hdc, 0, 0, win32con.SRCCOPY)
        else:
            SetStretchBltMode(hdc, win32con.HALFTONE)
            StretchBlt(hdc, 0, 0, rw, rh, self.hdc, 0, 0, bw, bh, win32con.SRCCOPY)

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

        bw, bh = self.size
        bitmap_stride = bw * 4
        offset = y * bitmap_stride + x * 4
        src = addressof(c_void_p.from_buffer(img_data))
        dst = c_void_p(self.pixels.value + offset)
        log(f"draw_region {offset=} {src=} - {dst=} {bitmap_stride=} {rowstride=}")
        if rowstride == bitmap_stride and x == 0 and y >= 0 and width == bw and y + height <= bh:
            # happy path: copy all at once
            memmove(dst, src, rowstride * height)
        else:
            # slow path: copy each row separately
            rowlen = min(width, bw - x) * 4
            for i in range(min(height, bh - y)):
                dst = c_void_p(self.pixels.value + offset + i * bitmap_stride)
                src = addressof(c_void_p.from_buffer(img_data)) + i * rowstride
                memmove(dst, src, rowlen)
        fire_paint_callbacks(callbacks)

    def paint_scroll(self, img_data, options: typedict, callbacks: PaintCallbacks) -> None:
        # newer servers use an option,
        # older ones overload the img_data:
        scroll_data = options.tupleget("scroll", img_data)
        self.with_gfx_context(self.do_scroll_paints, scroll_data, callbacks)

    def clip_scrolls(self, scrolls) -> list[tuple[int, int, int, int, int, int]]:
        """
        Clip the scroll rectangles so that both their source and their destination
        fit within the backing buffer, dropping the ones that end up empty.
        These should be errors, but desktop-scaling can cause a mismatch
        between the backing size and the real window size server-side,
        so we clip the dimensions instead.
        """
        bw, bh = self.size
        rects = []
        for x, y, w, h, xdelta, ydelta in scrolls:
            if xdelta == 0 and ydelta == 0:
                log.warn("Warning: scroll rectangle %s has no delta", (x, y, w, h))
                continue
            cx, cw = clip_span(x, w, xdelta, bw)
            cy, ch = clip_span(y, h, ydelta, bh)
            if cw <= 0 or ch <= 0:
                log.warn("Warning: scroll rectangle %s by %s does not fit in the backing buffer %s",
                         (x, y, w, h), (xdelta, ydelta), self.size)
                continue
            rects.append((cx, cy, cw, ch, xdelta, ydelta))
        return rects

    def snapshot_source(self, scrolls):
        """
        Copy the area covered by the source rectangles of the `scrolls` list
        into a new buffer, so that every rectangle can be painted
        from the backing contents as they were before any of them was applied.
        Returns the snapshot, its position within the backing and its rowstride.
        """
        x1 = min(x for x, _, _, _, _, _ in scrolls)
        y1 = min(y for _, y, _, _, _, _ in scrolls)
        x2 = max(x + w for x, _, w, _, _, _ in scrolls)
        y2 = max(y + h for _, y, _, h, _, _ in scrolls)
        stride = (x2 - x1) * 4
        rows = y2 - y1
        snapshot = create_string_buffer(stride * rows)
        bitmap_stride = self.size[0] * 4
        dst = addressof(snapshot)
        src = self.pixels.value + y1 * bitmap_stride + x1 * 4
        if stride == bitmap_stride:
            # full width: the rows are contiguous in both buffers, copy them all at once
            memmove(dst, src, stride * rows)
        else:
            for i in range(rows):
                memmove(dst + i * stride, src + i * bitmap_stride, stride)
        return snapshot, x1, y1, stride

    def do_scroll_paints(self, context, scrolls, callbacks: PaintCallbacks) -> None:
        log("do_scroll_paints%s", (context, scrolls, callbacks))
        if not self.bitmap:
            fire_paint_callbacks(callbacks, False, "window has already been destroyed")
            return
        if not scrolls:
            fire_paint_callbacks(callbacks)
            return
        rects = self.clip_scrolls(scrolls)
        if not rects:
            fire_paint_callbacks(callbacks, False, "no valid scroll rectangles")
            return
        # every rectangle is relative to the backing contents
        # as they were before any of them was applied,
        # so we copy from a snapshot taken before the loop:
        # applying them in place would corrupt the ones
        # whose source overlaps another one's destination
        # (see `paint_scroll` in `WindowBackingBase`)
        snapshot, ox, oy, stride = self.snapshot_source(rects)
        bitmap_stride = self.size[0] * 4
        for x, y, w, h, xdelta, ydelta in rects:
            src = addressof(snapshot) + (y - oy) * stride + (x - ox) * 4
            dst = self.pixels.value + (y + ydelta) * bitmap_stride + (x + xdelta) * 4
            rowlen = w * 4
            log(f"scroll {(x, y, w, h)} by {(xdelta, ydelta)}: {src=} - {dst=} {stride=} {bitmap_stride=}")
            if rowlen == stride == bitmap_stride:
                # full width: the rows are contiguous in both buffers, copy them all at once
                memmove(dst, src, rowlen * h)
            else:
                for i in range(h):
                    memmove(dst + i * bitmap_stride, src + i * stride, rowlen)
        if len(rects) < len(scrolls):
            # some rectangles were dropped, ask the server to repaint the area:
            fire_paint_callbacks(callbacks, False, "some scroll rectangles could not be applied")
            return
        fire_paint_callbacks(callbacks)

    def close(self) -> None:
        if bitmap := self.bitmap:
            self.bitmap = 0
            DeleteObject(bitmap)
        super().close()
