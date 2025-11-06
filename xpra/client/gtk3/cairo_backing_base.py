# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from math import pi, sin
from time import monotonic
from typing import Any
from collections.abc import Callable
from cairo import Context, ImageSurface, Format, Operator, OPERATOR_OVER, LINE_CAP_ROUND

from xpra.client.gui.paint_colors import get_paint_box_color
from xpra.client.gui.window.backing import WindowBackingBase, fire_paint_callbacks, ALERT_MODE
from xpra.client.gui.window_border import WindowBorder
from xpra.common import roundup, PaintCallbacks, noop
from xpra.util.str_fn import memoryview_to_bytes
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.os_util import gi_import
from xpra.log import Logger

try:
    from xpra.gtk.cairo_image import make_image_surface
except ImportError:
    make_image_surface = noop

GLib = gi_import("GLib")
Gdk = gi_import("Gdk")

log = Logger("paint", "cairo")

COPY_OLD_BACKING = envbool("XPRA_CAIRO_COPY_OLD_BACKING", True)

FORMATS = {-1: "INVALID"}
for attr in dir(Format):
    if attr.isupper():
        FORMATS[getattr(Format, attr)] = attr


def clamp(val: float) -> float:
    return max(0.0, min(1.0, val))


def cairo_paint_pointer_overlay(context, cursor_data, px: int, py: int, start_time) -> None:
    if not cursor_data or make_image_surface == noop:
        return
    elapsed = max(0, monotonic() - start_time)
    if elapsed > 6:
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
    alert_image = ()

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

    def cairo_draw(self, context, w: int, h: int) -> None:
        backing = self._backing
        log("cairo_draw: window size=%s, backing=%s, size=%s, render-size=%s, offsets=%s, pointer_overlay=%s",
            backing, (w, h), self.size, self.render_size, self.offsets, self.pointer_overlay)
        if backing is None:
            return
        self.paint_backing_offset_border(context, w, h)
        if not self.clip_to_backing(context, w, h):
            return
        self.cairo_draw_backing(context, backing)
        self.cairo_draw_pointer(context)
        self.cairo_draw_alert(context)

    def paint_backing_offset_border(self, context, w: int, h: int) -> None:
        left, top, right, bottom = self.offsets
        if left != 0 or top != 0 or right != 0 or bottom != 0:
            from xpra.client.gtk3.window.common import PADDING_COLORS
            context.save()
            context.set_source_rgb(*PADDING_COLORS)
            coords = (
                (0, 0, left, h),  # left hand side padding
                (0, 0, w, top),  # top padding
                (w - right, 0, right, h),  # RHS
                (0, h - bottom, w, bottom),  # bottom
            )
            log("paint_backing_offset_border(%s, %i, %i) offsets=%s, size=%s, rgb=%s, coords=%s",
                context, w, h, self.offsets, (w, h), PADDING_COLORS, coords)
            for rx, ry, rw, rh in coords:
                if rw > 0 and rh > 0:
                    context.rectangle(rx, ry, rw, rh)
            context.fill()
            context.restore()

    def clip_to_backing(self, context, w: int, h: int) -> bool:
        left, top, right, bottom = self.offsets
        clip_rect = (left, top, w - left - right, h - top - bottom)
        context.rectangle(*clip_rect)
        log("clip_to_backing%s rectangle=%s", (context, w, h), clip_rect)
        context.clip()
        ww, wh = self.render_size
        w, h = self.size
        if ww == 0 or w == 0 or wh == 0 or h == 0:
            return False
        if w != ww or h != wh:
            context.scale(ww / w, wh / h)
        x, y = self.offsets[:2]
        if x != 0 or y != 0:
            context.translate(x, y)
        return True

    def cairo_draw_backing(self, context, backing) -> None:
        context.set_operator(Operator.SOURCE)
        context.set_source_surface(backing, 0, 0)
        context.paint()

    def cairo_draw_pointer(self, context):
        if self.pointer_overlay and self.cursor_data:
            px, py, _size, start_time = self.pointer_overlay[2:]
            cairo_paint_pointer_overlay(context, self.cursor_data, px, py, start_time)

    def cairo_draw_border(self, context, border) -> None:
        log("cairo_draw_border(%s, %s)", context, border)
        if border is None or not border.shown:
            return
        w, h = self.size
        hsize = min(border.size, w)
        vsize = min(border.size, h)
        if w <= hsize or h <= vsize:
            rects = ((0, 0, w, h), )
        else:
            rects = (
                (0, 0, w, vsize),                             # top
                (w - hsize, vsize, hsize, h - vsize * 2),     # right
                (0, h - vsize, w, vsize),                     # bottom
                (0, vsize, hsize, h - vsize * 2),             # left
            )

        for x, y, w, h in rects:
            if w <= 0 or h <= 0:
                continue
            r = Gdk.Rectangle()
            r.x = x
            r.y = y
            r.width = w
            r.height = h
            rect = r
            if rect.width == 0 or rect.height == 0:
                continue
            context.save()
            context.rectangle(x, y, w, h)
            context.clip()
            context.set_source_rgba(border.red, border.green, border.blue, border.alpha)
            context.fill()
            context.paint()
            context.restore()

    def cairo_draw_fps(self, context):
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

    def cairo_draw_alert(self, context) -> None:
        if not self.alert_state:
            return
        if "shade" in ALERT_MODE:
            self.draw_alert_shade(context)
        if "dark-shade" in ALERT_MODE:
            self.draw_alert_shade(context, 0.8)
        if "light-shade" in ALERT_MODE:
            self.draw_alert_shade(context, 0.2)
        if "icon" in ALERT_MODE:
            self.draw_alert_icon(context)
        if "spinner" in ALERT_MODE:
            self.draw_alert_spinner(context)
        if "small-spinner" in ALERT_MODE:
            self.draw_alert_spinner(context, 40)
        if "big-spinner" in ALERT_MODE:
            self.draw_alert_spinner(context, 90)
        border = self.border
        if "border" in ALERT_MODE:
            alpha = clamp(0.1 + (0.9 + sin(monotonic() * 5)) / 2)
            border = WindowBorder(True, 1.0, 0.0, 0.0, alpha, 10)
        self.cairo_draw_border(context, border)

    def draw_alert_shade(self, context, shade=0.5) -> None:
        w, h = self.size
        context.save()
        context.set_operator(OPERATOR_OVER)
        context.set_source_rgba(0.2, 0.2, 0.2, shade)
        context.rectangle(0, 0, w, h)
        context.fill()
        context.restore()

    @staticmethod
    def get_alert_image():
        if not CairoBackingBase.alert_image:
            iw, ih, pixels = WindowBackingBase.get_alert_icon()
            if iw and ih and pixels:
                CairoBackingBase.alert_image = iw, ih, make_image_surface(Format.ARGB32, "RGBA", pixels, iw, ih, iw * 4)
            else:
                CairoBackingBase.alert_image = 0, 0, None
        return CairoBackingBase.alert_image

    def draw_alert_icon(self, context) -> None:
        iw, ih, image = self.get_alert_image()
        if iw == 0 or ih == 0 or not image:
            return
        from math import sin
        _, h = self.size
        x = 10
        y = h - ih - 10
        alpha = (1 + sin(monotonic() * 5)) / 2
        context.save()
        context.translate(x, y)
        context.set_operator(Operator.OVER)
        context.set_source_surface(image, 0, 0)
        context.paint_with_alpha(alpha)
        context.restore()

    def draw_alert_spinner(self, context, outer_pct=70) -> None:
        log("%s.cairo_draw_alert(%s)", self, context)
        w, h = self.size
        context.save()
        dim = min(w / 3.0, h / 3.0, 100.0)
        context.set_line_width(dim / 10.0)
        context.set_line_cap(LINE_CAP_ROUND)
        context.translate(w / 2, h / 2)

        def coords(x: float, y: float) -> tuple[float, float]:
            # scale 0..1 to real coordinates:
            return x * w / 2, y * h / 2

        from xpra.client.gui.spinner import gen_trapezoids, NLINES
        now = monotonic()
        step = 0
        for inner_left, inner_right, outer_left, outer_right in gen_trapezoids(outer_pct=outer_pct):  # 8 lines
            alpha = 0.3 + (1 + sin(step * 2 * pi / NLINES + now * 4)) / 3
            context.set_source_rgba(alpha, alpha, alpha, alpha)
            context.move_to(*coords(*inner_left))
            context.line_to(*coords(*outer_left))
            context.line_to(*coords(*outer_right))
            context.line_to(*coords(*inner_right))
            context.close_path()
            context.fill()
            step += 1
        context.restore()
