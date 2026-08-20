# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any, Final
from collections.abc import Sequence

from xpra.client.gui.window.backing import (
    WindowBackingBase, PaintCallbacks,
    fire_paint_callbacks, clip_span,
)
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("paint", "terminal")

# the terminal renders RGBA pixels, so this is the only pixel size we ever store:
BPP: Final[int] = 4


def rects_overlap(r1: Sequence[int], r2: Sequence[int]) -> bool:
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    return x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1


def bounding_box(r1: Sequence[int], r2: Sequence[int]) -> tuple[int, int, int, int]:
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    x = min(x1, x2)
    y = min(y1, y2)
    return x, y, max(x1 + w1, x2 + w2) - x, max(y1 + h1, y2 + h2) - y


def merge_rects(rects: Sequence[Sequence[int]]) -> list[tuple[int, int, int, int]]:
    """
    Replace every group of overlapping rectangles with the bounding box that covers them.
    Rectangles that merely touch are left alone: only real overlaps would be painted twice.
    """
    merged: list[tuple[int, int, int, int]] = []
    for rect in rects:
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            continue
        current = (x, y, w, h)
        absorbed = True
        while absorbed:
            absorbed = False
            for index, other in enumerate(merged):
                if rects_overlap(current, other):
                    current = bounding_box(current, other)
                    merged.pop(index)
                    absorbed = True
                    break
        merged.append(current)
    return merged


def to_rgba(rgb_format: str, data, width: int, height: int, rowstride: int) -> bytes:
    """
    Convert a rectangle of pixels into row-contiguous RGBA, removing any row padding.
    `X` in `BGRX` / `RGBX` is padding with undefined contents, never alpha:
    those formats are made fully opaque instead of copying the padding byte.
    """
    bpp = len(rgb_format)
    if bpp not in (3, 4) or not all(c in "RGBAX" for c in rgb_format):
        raise ValueError(f"unsupported rgb format {rgb_format!r}")
    stride = width * bpp
    if rowstride <= 0:
        rowstride = stride
    src = memoryview(data).cast("B")
    needed = rowstride * (height - 1) + stride
    if len(src) < needed:
        raise ValueError(f"not enough pixel data: {len(src)} bytes, expected {needed}")
    # work on `bytes` from here on: assigning a memoryview to a slice of a
    # bytearray trips the type guards of a `cythonize_more` build:
    if rowstride != stride:
        raw = src.tobytes()
        tight = bytearray(stride * height)
        for row in range(height):
            tight[row * stride:(row + 1) * stride] = raw[row * rowstride:row * rowstride + stride]
        flat = bytes(tight)
    else:
        flat = src[:stride * height].tobytes()
    if rgb_format == "RGBA":
        return flat
    pixels = width * height
    # `object`, not `bytearray`: Cython's optimized bytearray slice assignment
    # only accepts a bytearray right-hand side under a `cythonize_more` build:
    out: object = bytearray(pixels * BPP)
    out[0::BPP] = flat[rgb_format.index("R")::bpp]
    out[1::BPP] = flat[rgb_format.index("G")::bpp]
    out[2::BPP] = flat[rgb_format.index("B")::bpp]
    if "A" in rgb_format:
        out[3::BPP] = flat[rgb_format.index("A")::bpp]
    else:
        out[3::BPP] = b"\xff" * pixels
    return bytes(out)


class TerminalBacking(WindowBackingBase):
    """
    Renders into a plain RGBA byte buffer which the window turns into
    kitty graphics protocol commands from the UI thread.
    """
    RGB_MODES: Sequence[str] = ("BGRA", "BGRX", "RGBA", "RGBX", "RGB", "BGR")
    HAS_ALPHA: bool = True

    def __init__(self, wid: int, window_alpha: bool, pixel_depth: int = 0):
        super().__init__(wid, window_alpha and self.HAS_ALPHA)
        self.pixel_depth = pixel_depth
        self.pixels = bytearray()
        # incremented every time the buffer is (re)allocated,
        # so the window knows it has to transmit a whole new image:
        self.buffer_serial: int = 0
        self.damage: list[tuple[int, int, int, int]] = []
        self.content_type = ""
        # the superclass requires this attribute to be set to enable rendering:
        self._backing = object()

    def __repr__(self):
        return f"TerminalBacking({self.wid:#x})"

    def init(self, ww: int, wh: int, bw: int, bh: int) -> None:
        """
        `(ww, wh)` is the on-screen (client, desktop-scaled) size,
        `(bw, bh)` is the backing buffer (server pixel) size:
        only the latter requires reallocating the pixel buffer.
        """
        self.render_size = (ww, wh)
        if (bw, bh) != self.size or len(self.pixels) != bw * bh * BPP:
            log("init(%i, %i, %i, %i) reallocating from %s", ww, wh, bw, bh, self.size)
            oldw, oldh = self.size
            old_pixels = self.pixels
            self.size = (bw, bh)
            self.pixels = bytearray(bw * bh * BPP)
            self.buffer_serial += 1
            self.damage = []
            self.copy_old_backing(oldw, oldh, old_pixels)

    def copy_old_backing(self, oldw: int, oldh: int, old_pixels) -> None:
        """
        Carry the pixels of the previous buffer over into the newly allocated one,
        honouring the window gravity, so that a resized window keeps its contents
        until the server repaints it (this is what the cairo and OpenGL backings do).
        """
        bw, bh = self.size
        if oldw <= 0 or oldh <= 0 or len(old_pixels) != oldw * oldh * BPP:
            return
        sx, sy, dx, dy, w, h = self.gravity_copy_coords(oldw, oldh, bw, bh)
        log("copy_old_backing() %ix%i -> %ix%i, gravity=%s, copying %ix%i from %s to %s",
            oldw, oldh, bw, bh, self.gravity, w, h, (sx, sy), (dx, dy))
        src_stride = oldw * BPP
        dst_stride = bw * BPP
        rowlen = w * BPP
        pixels = self.pixels
        for row in range(h):
            src = (sy + row) * src_stride + sx * BPP
            dst = (dy + row) * dst_stride + dx * BPP
            pixels[dst:dst + rowlen] = old_pixels[src:src + rowlen]

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info |= {
            "type": "terminal",
            "buffer-serial": self.buffer_serial,
            "damage": len(self.damage),
        }
        return info

    def update_fps_buffer(self, width: int, height: int, pixels) -> None:
        """ the terminal backend does not render the fps counter """

    # ------------------------------------------------------------------
    # damage tracking

    def add_damage(self, x: int, y: int, width: int, height: int) -> None:
        if width > 0 and height > 0:
            self.damage.append((x, y, width, height))

    def get_damage(self) -> list[tuple[int, int, int, int]]:
        """ drain the damage rectangles accumulated since the last call - UI thread """
        damage = self.damage
        self.damage = []
        return merge_rects(damage)

    # ------------------------------------------------------------------
    # pixel access

    def clip(self, x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
        """ clip a rectangle to the backing buffer, the result may be empty """
        bw, bh = self.size
        x1 = max(0, min(bw, x))
        y1 = max(0, min(bh, y))
        x2 = max(0, min(bw, x + width))
        y2 = max(0, min(bh, y + height))
        return x1, y1, max(0, x2 - x1), max(0, y2 - y1)

    def pixels_for(self, x: int, y: int, width: int, height: int) -> bytes:
        """ a row-contiguous RGBA copy of a sub-rectangle of the buffer """
        bw, bh = self.size
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > bw or y + height > bh:
            raise ValueError(f"invalid rectangle {(x, y, width, height)} for {bw}x{bh} backing")
        if width == bw:
            offset = y * bw * BPP
            return bytes(self.pixels[offset:offset + height * bw * BPP])
        stride = bw * BPP
        rowlen = width * BPP
        out = bytearray(rowlen * height)
        pixels = self.pixels
        for row in range(height):
            offset = (y + row) * stride + x * BPP
            out[row * rowlen:(row + 1) * rowlen] = pixels[offset:offset + rowlen]
        return bytes(out)

    def blit(self, rgba, x: int, y: int, width: int, height: int) -> None:
        """ copy row-contiguous RGBA pixels into the buffer, the rectangle must already be clipped """
        bw = self.size[0]
        stride = bw * BPP
        rowlen = width * BPP
        pixels = self.pixels
        if width == bw and stride == rowlen:
            offset = y * stride
            pixels[offset:offset + rowlen * height] = rgba
            return
        for row in range(height):
            offset = (y + row) * stride + x * BPP
            pixels[offset:offset + rowlen] = rgba[row * rowlen:(row + 1) * rowlen]

    # ------------------------------------------------------------------
    # paint

    def do_paint_rgb(self, context, encoding: str, rgb_format: str, img_data,
                     x: int, y: int, width: int, height: int, render_width: int, render_height: int, rowstride: int,
                     options: typedict, callbacks: PaintCallbacks) -> None:
        """ must be called from the UI thread, and must fire the callbacks exactly once """
        log("do_paint_rgb%s", (context, encoding, rgb_format, type(img_data),
                               x, y, width, height, render_width, render_height, rowstride, options))
        try:
            if not options.boolget("paint", True):
                fire_paint_callbacks(callbacks)
                return
            if self._backing is None:
                fire_paint_callbacks(callbacks, -1, "this backing is closed")
                return
            if (width, height) != (render_width, render_height):
                # we never request desktop-scaling, so this should not happen:
                fire_paint_callbacks(callbacks, False, "scaling is not supported")
                return
            if rgb_format not in self.RGB_MODES:
                fire_paint_callbacks(callbacks, False, f"unsupported pixel format {rgb_format!r}")
                return
            x, y = self.gravity_adjust(x, y, options)
            bpp = len(rgb_format)
            if rowstride <= 0:
                rowstride = width * bpp
            # the pixel data comes from the server, so make sure that the buffer
            # really does contain the pixels we are about to copy from it
            # (the last row only needs `width * bpp` bytes):
            needed = rowstride * (height - 1) + width * bpp
            if rowstride < width * bpp or len(img_data) < needed:
                fire_paint_callbacks(callbacks, False,
                                     f"not enough pixel data: {len(img_data)} bytes, expected {needed}"
                                     f" for {width}x{height} {rgb_format} with rowstride={rowstride}")
                return
            cx, cy, cw, ch = self.clip(x, y, width, height)
            if cw <= 0 or ch <= 0:
                fire_paint_callbacks(callbacks, -1, "paint rectangle is outside of the backing")
                return
            # skip the rows and columns that fall outside of the buffer:
            skip_x = cx - x
            skip_y = cy - y
            rgba = to_rgba(rgb_format, img_data, width, height, rowstride)
            if (cw, ch) != (width, height):
                stride = width * BPP
                rowlen = cw * BPP
                cropped = bytearray(rowlen * ch)
                for row in range(ch):
                    offset = (skip_y + row) * stride + skip_x * BPP
                    cropped[row * rowlen:(row + 1) * rowlen] = rgba[offset:offset + rowlen]
                rgba = bytes(cropped)
            self.blit(rgba, cx, cy, cw, ch)
            self.add_damage(cx, cy, cw, ch)
            if options.intget("flush", 0) == 0:
                self.record_fps_event()
            fire_paint_callbacks(callbacks)
        except Exception as e:
            log("do_paint_rgb%s", (context, encoding, rgb_format, type(img_data),
                                   x, y, width, height, render_width, render_height, rowstride,
                                   options, callbacks), exc_info=True)
            if self._backing is None:
                fire_paint_callbacks(callbacks, -1, "paint error on closed backing ignored")
            else:
                log.error("Error: failed to paint %s pixels", rgb_format)
                log.estr(e)
                fire_paint_callbacks(callbacks, False, f"paint error: {e}")

    # ------------------------------------------------------------------
    # scroll

    def paint_scroll(self, scroll_data, options: typedict, callbacks: PaintCallbacks) -> None:
        # newer servers use an option, older ones overload the image data:
        scrolls = options.tupleget("scroll", scroll_data)
        self.with_gfx_context(self.do_scroll_paints, scrolls, callbacks)

    def clip_scrolls(self, scrolls: Sequence[Sequence[int]]) -> list[tuple[int, int, int, int, int, int]]:
        """
        Clip the scroll rectangles so that both their source and their destination
        fit within the backing buffer, dropping the ones that end up empty.
        """
        bw, bh = self.size
        rects: list[tuple[int, int, int, int, int, int]] = []
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

    def do_scroll_paints(self, context, scrolls, callbacks: PaintCallbacks) -> None:
        log("do_scroll_paints%s", (context, scrolls, callbacks))
        if self._backing is None:
            fire_paint_callbacks(callbacks, -1, "this backing is closed")
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
        snapshot = bytes(self.pixels)
        stride = self.size[0] * BPP
        pixels = self.pixels
        for x, y, w, h, xdelta, ydelta in rects:
            rowlen = w * BPP
            for row in range(h):
                src = (y + row) * stride + x * BPP
                dst = (y + row + ydelta) * stride + (x + xdelta) * BPP
                pixels[dst:dst + rowlen] = snapshot[src:src + rowlen]
            self.add_damage(x + xdelta, y + ydelta, w, h)
        if len(rects) < len(scrolls):
            # some rectangles were dropped, ask the server to repaint the area:
            fire_paint_callbacks(callbacks, False, "some scroll rectangles could not be applied")
            return
        fire_paint_callbacks(callbacks)

    # ------------------------------------------------------------------

    def close(self) -> None:
        self.pixels = bytearray()
        self.damage = []
        super().close()
