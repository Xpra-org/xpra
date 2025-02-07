# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Any
from collections.abc import Callable
from cairo import Context, ImageSurface, Format, Operator

from xpra.client.gui.paint_colors import get_paint_box_color
from xpra.client.gui.window_backing_base import WindowBackingBase, fire_paint_callbacks
from xpra.common import roundup, PaintCallbacks
from xpra.util.str_fn import memoryview_to_bytes
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.os_util import gi_import
from xpra.log import Logger

GLib = gi_import("GLib")
Gdk = gi_import("Gdk")

log = Logger("paint", "cairo")

COPY_OLD_BACKING = envbool("XPRA_CAIRO_COPY_OLD_BACKING", True)

FORMATS = {-1: "INVALID"}
for attr in dir(Format):
    if attr.isupper():
        FORMATS[getattr(Format, attr)] = attr


def cairo_paint_pointer_overlay(context, cursor_data, px: int, py: int, start_time) -> None:
    if not cursor_data:
        return
    elapsed = max(0, monotonic() - start_time)
    if elapsed > 6:
        return
    # pylint: disable=import-outside-toplevel
    try:
        from xpra.client.gtk3.cairo_image import make_image_surface
    except ImportError:
        return

    cw = cursor_data[3]
    ch = cursor_data[4]
    xhot = cursor_data[5]
    yhot = cursor_data[6]
    pixels = cursor_data[8]
    x = px - xhot
    y = py - yhot

    alpha = max(0.0, (5.0 - elapsed) / 5.0)
    log("cairo_paint_pointer_overlay%s drawing pointer with cairo, alpha=%s",
        (context, x, y, start_time), alpha)
    bgra = memoryview_to_bytes(pixels)
    img = make_image_surface(Format.ARGB32, "BGRA", bgra, cw, ch, cw * 4)
    context.translate(x, y)
    context.set_source_surface(img, 0, 0)
    context.set_operator(Operator.OVER)
    context.paint_with_alpha(alpha)


class CairoBackingBase(WindowBackingBase):
    HAS_ALPHA = envbool("XPRA_ALPHA", True)

    def __init__(self, wid: int, window_alpha: bool, _pixel_depth=0):
        super().__init__(wid, window_alpha and self.HAS_ALPHA)
        self.size = 0, 0
        self.render_size = 0, 0
        self.fps_image = None

    def init(self, ww: int, wh: int, bw: int, bh: int) -> None:
        mod = self.size != (bw, bh) or self.render_size != (ww, wh)
        self.size = bw, bh
        self.render_size = ww, wh
        if mod:
            self.create_surface()

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info |= {
            "type": "Cairo",
            "rgb-formats": self.get_rgb_formats(),
        }
        return info

    def create_surface(self) -> Context | None:
        bw, bh = self.size
        old_backing = self._backing
        # should we honour self.depth here?
        self._backing = None
        if bw == 0 or bh == 0:
            # this can happen during cleanup
            return None
        backing = ImageSurface(Format.ARGB32, bw, bh)
        self._backing = backing
        cr = Context(backing)
        if self._alpha_enabled:
            cr.set_operator(Operator.CLEAR)
            cr.set_source_rgba(1, 1, 1, 0)
        else:
            cr.set_operator(Operator.SOURCE)
            cr.set_source_rgba(1, 1, 1, 1)
        cr.rectangle(0, 0, bw, bh)
        cr.fill()
        if COPY_OLD_BACKING and old_backing is not None:
            cr.save()
            oldw, oldh = old_backing.get_width(), old_backing.get_height()
            sx, sy, dx, dy, w, h = self.gravity_copy_coords(oldw, oldh, bw, bh)
            cr.translate(dx - sx, dy - sy)
            cr.rectangle(sx, sy, w, h)
            cr.clip()
            cr.set_operator(Operator.SOURCE)
            cr.set_source_surface(old_backing, 0, 0)
            cr.paint()
            cr.restore()
            if self.paint_box_line_width > 0 and (oldw != bw or oldh != bh):
                if bw > oldw:
                    self.cairo_paint_box(cr, "padding", oldw, 0, bw - oldw, bh)
                if bh > oldh:
                    self.cairo_paint_box(cr, "padding", 0, oldh, bw, bh - oldh)
            backing.flush()
        return cr

    def close(self) -> None:
        backing = self._backing
        if backing:
            backing.finish()
            self._backing = None
        super().close()

    def cairo_paint_pixbuf(self, pixbuf, x: int, y: int, options) -> None:
        """ must be called from UI thread """
        log("source pixbuf: %s", pixbuf)
        w, h = pixbuf.get_width(), pixbuf.get_height()
        self.cairo_paint_from_source(Gdk.cairo_set_source_pixbuf, pixbuf, x, y, w, h, w, h, options)

    def cairo_paint_surface(self, img_surface, x: int, y: int, width: int, height: int, options) -> None:
        iw, ih = img_surface.get_width(), img_surface.get_height()
        log("source image surface: %s",
            (img_surface.get_format(), iw, ih, img_surface.get_stride(), img_surface.get_content(),))

        def set_source_surface(gc, surface, sx: int, sy: int) -> None:
            gc.set_source_surface(surface, sx, sy)

        self.cairo_paint_from_source(set_source_surface, img_surface, x, y, iw, ih, width, height, options)

    def cairo_paint_from_source(self, set_source_fn: Callable[[Any, Any, int, int], None], source,
                                x: int, y: int, iw: int, ih: int, width: int, height: int, options) -> None:
        """ must be called from UI thread """
        backing = self._backing
        log("cairo_paint_surface%s backing=%s, paint box line width=%i",
            (set_source_fn, source, x, y, iw, ih, width, height, options),
            backing, self.paint_box_line_width)
        if not backing:
            return
        gc = Context(backing)
        if self.paint_box_line_width:
            gc.save()

        gc.rectangle(x, y, width, height)
        gc.clip()

        gc.set_operator(Operator.CLEAR)
        gc.rectangle(x, y, width, height)
        gc.fill()

        gc.set_operator(Operator.SOURCE)
        gc.translate(x, y)
        if iw != width or ih != height:
            gc.scale(width / iw, height / ih)
        gc.rectangle(0, 0, width, height)
        set_source_fn(gc, source, 0, 0)
        gc.paint()

        if self.paint_box_line_width:
            gc.restore()
            encoding = options.get("encoding")
            self.cairo_paint_box(gc, encoding, x, y, width, height)

        flush = options.get("flush", 0)
        if flush == 0:
            self.record_fps_event()

    def cairo_paint_box(self, gc, encoding: str, x: int, y: int, w: int, h: int) -> None:
        color = get_paint_box_color(encoding)
        gc.set_line_width(self.paint_box_line_width)
        gc.set_source_rgba(*color)
        gc.rectangle(x, y, w, h)
        gc.stroke()

    def do_paint_rgb(self, context, encoding: str, rgb_format: str, img_data,
                     x: int, y: int, width: int, height: int, render_width: int, render_height: int, rowstride: int,
                     options: typedict, callbacks: PaintCallbacks) -> None:
        """ must be called from the UI thread
            this method is only here to ensure that we always fire the callbacks,
            the actual paint code is in _do_paint_rgb[16|24|30|32]
        """
        if not options.boolget("paint", True):
            fire_paint_callbacks(callbacks)
            return
        if self._backing is None:
            fire_paint_callbacks(callbacks, -1, "no backing")
            return
        x, y = self.gravity_adjust(x, y, options)
        if rgb_format == "r210":
            bpp = 30
        elif rgb_format == "BGR565":
            bpp = 16
        else:
            bpp = len(rgb_format) * 8  # ie: "BGRA" -> 32
        if rowstride == 0:
            rowstride = width * roundup(bpp, 8) // 8
        try:
            fmt = {
                16: Format.RGB16_565,
                24: Format.RGB24,
                30: Format.RGB30,
                32: Format.ARGB32 if self._alpha_enabled else Format.RGB24,
            }.get(bpp, Format.INVALID)
            if fmt == Format.INVALID:
                raise ValueError(f"invalid rgb format {rgb_format!r} with bit depth {bpp}")
            options["rgb_format"] = rgb_format
            alpha = bpp == 32 and self._alpha_enabled
            self._do_paint_rgb(fmt, alpha, img_data,
                               x, y, width, height, render_width, render_height, rowstride, options)
            fire_paint_callbacks(callbacks, True)
        except Exception as e:
            if not self._backing:
                fire_paint_callbacks(callbacks, -1, "paint error on closed backing ignored")
            else:
                log.error("Error painting rgb%s", bpp, exc_info=True)
                message = f"paint rgb{bpp} error: {e}"
                fire_paint_callbacks(callbacks, False, message)

    def _do_paint_rgb(self, *args) -> None:
        # see CairoBacking
        raise NotImplementedError()

    def paint_scroll(self, img_data, options: typedict, callbacks: PaintCallbacks) -> None:
        # newer servers use an option,
        # older ones overload the img_data:
        scroll_data = options.tupleget("scroll", img_data)
        GLib.idle_add(self.do_paint_scroll, scroll_data, callbacks)

    def do_paint_scroll(self, scrolls, callbacks: PaintCallbacks) -> None:
        old_backing = self._backing
        if not old_backing:
            fire_paint_callbacks(callbacks, False, message="no backing")
            return
        gc = self.create_surface()
        if not gc:
            fire_paint_callbacks(callbacks, False, message="no context")
            return
        gc.set_operator(Operator.SOURCE)
        for sx, sy, sw, sh, xdelta, ydelta in scrolls:
            gc.set_source_surface(old_backing, xdelta, ydelta)
            x = sx + xdelta
            y = sy + ydelta
            gc.rectangle(x, y, sw, sh)
            gc.fill()
            if self.paint_box_line_width > 0:
                self.cairo_paint_box(gc, "scroll", x, y, sw, sh)
        del gc
        self._backing.flush()
        fire_paint_callbacks(callbacks)

    def cairo_draw(self, context) -> None:
        backing = self._backing
        log("cairo_draw: backing=%s, size=%s, render-size=%s, offsets=%s, pointer_overlay=%s",
            backing, self.size, self.render_size, self.offsets, self.pointer_overlay)
        if backing is None:
            return
        # try:
        #    log("clip rectangles=%s", context.copy_clip_rectangle_list())
        # except:
        #    log.error("clip:", exc_info=True)
        ww, wh = self.render_size
        w, h = self.size
        if ww == 0 or w == 0 or wh == 0 or h == 0:
            return
        if w != ww or h != wh:
            context.scale(ww / w, wh / h)
        x, y = self.offsets[:2]
        if x != 0 or y != 0:
            context.translate(x, y)
        context.set_operator(Operator.SOURCE)
        context.set_source_surface(backing, 0, 0)
        context.paint()

        if self.pointer_overlay and self.cursor_data:
            px, py, _size, start_time = self.pointer_overlay[2:]
            spx = round(w * px / ww)
            spy = round(h * py / wh)
            cairo_paint_pointer_overlay(context, self.cursor_data, x + spx, y + spy, start_time)

        if self.is_show_fps() and self.fps_image:
            x, y = 10, 10
            context.translate(x, y)
            context.set_operator(Operator.OVER)
            context.set_source_surface(self.fps_image, 0, 0)
            context.paint()
            self.cancel_fps_refresh()

            def refresh_screen() -> None:
                self.fps_refresh_timer = 0
                b = self._backing
                if b:
                    self.update_fps()
                    rw, rh = self.render_size
                    self.repaint(0, 0, rw, rh)

            self.cancel_fps_refresh()
            self.fps_refresh_timer = GLib.timeout_add(1000, refresh_screen)
