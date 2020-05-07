# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo
from gi.repository import GLib, Gdk

from xpra.client.paint_colors import get_paint_box_color
from xpra.client.window_backing_base import WindowBackingBase, fire_paint_callbacks, SCROLL_ENCODING
from xpra.client.gtk_base.cairo_paint_common import setup_cairo_context, cairo_paint_pointer_overlay
from xpra.os_util import memoryview_to_bytes
from xpra.util import envbool
from xpra.log import Logger

log = Logger("paint", "cairo")

FORMATS = {-1   : "INVALID"}
for attr in dir(cairo):
    if attr.startswith("FORMAT_"):
        FORMATS[getattr(cairo, attr)] = attr.replace("FORMAT_", "")


class CairoBackingBase(WindowBackingBase):

    HAS_ALPHA = envbool("XPRA_ALPHA", True)

    def __init__(self, wid, window_alpha, _pixel_depth=0):
        super().__init__(wid, window_alpha and self.HAS_ALPHA)
        self.idle_add = GLib.idle_add

    def init(self, ww : int, wh : int, bw : int, bh : int):
        self.size = bw, bh
        self.render_size = ww, wh
        self.create_surface()

    def create_surface(self):
        bw, bh = self.size
        old_backing = self._backing
        #should we honour self.depth here?
        self._backing = None
        if bw==0 or bh==0:
            #this can happen during cleanup
            return None
        self._backing = cairo.ImageSurface(cairo.FORMAT_ARGB32, bw, bh)
        cr = cairo.Context(self._backing)
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.rectangle(0, 0, bw, bh)
        cr.fill()
        if old_backing is not None:
            oldw, oldh = old_backing.get_width(), old_backing.get_height()
            sx, sy, dx, dy, w, h = self.gravity_copy_coords(oldw, oldh, bw, bh)
            cr.translate(dx-sx, dy-sy)
            cr.rectangle(sx, sy, w, h)
            cr.fill()
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_surface(old_backing, 0, 0)
            cr.paint()
            self._backing.flush()
        return cr

    def close(self):
        if self._backing:
            self._backing.finish()
        WindowBackingBase.close(self)


    def cairo_paint_pixbuf(self, pixbuf, x : int, y : int, options):
        """ must be called from UI thread """
        log("source pixbuf: %s", pixbuf)
        w, h = pixbuf.get_width(), pixbuf.get_height()
        self.cairo_paint_from_source(Gdk.cairo_set_source_pixbuf, pixbuf, x, y, w, h, options)

    def cairo_paint_surface(self, img_surface, x : int, y : int, options):
        w, h = img_surface.get_width(), img_surface.get_height()
        log("source image surface: %s",
            (img_surface.get_format(), w, h, img_surface.get_stride(), img_surface.get_content(), ))
        def set_source_surface(gc, surface, sx, sy):
            gc.set_source_surface(surface, sx, sy)
        self.cairo_paint_from_source(set_source_surface, img_surface, x, y, w, h, options)

    def cairo_paint_from_source(self, set_source_fn, source, x : int, y : int, w : int, h : int, options):
        """ must be called from UI thread """
        log("cairo_paint_surface(%s, %s, %s, %s, %s, %s, %s) backing=%s, paint box line width=%i",
            set_source_fn, source, x, y, w, h, options, self._backing, self.paint_box_line_width)
        gc = cairo.Context(self._backing)
        if self.paint_box_line_width:
            gc.save()

        gc.rectangle(x, y, w, h)
        gc.clip()

        gc.set_operator(cairo.OPERATOR_CLEAR)
        gc.rectangle(x, y, w, h)
        gc.fill()

        gc.set_operator(cairo.OPERATOR_SOURCE)
        gc.translate(x, y)
        gc.rectangle(0, 0, w, h)
        set_source_fn(gc, source, 0, 0)
        gc.paint()

        if self.paint_box_line_width:
            gc.restore()
            encoding = options.get("encoding")
            self.cairo_paint_box(gc, encoding, x, y, w, h)

    def cairo_paint_box(self, gc, encoding, x, y, w, h):
        color = get_paint_box_color(encoding)
        gc.set_line_width(self.paint_box_line_width)
        gc.set_source_rgba(*color)
        gc.rectangle(x, y, w, h)
        gc.stroke()


    def _do_paint_rgb24(self, img_data, x : int, y : int, width : int, height : int, rowstride : int, options):
        return self._do_paint_rgb(cairo.FORMAT_RGB24, False, img_data, x, y, width, height, rowstride, options)

    def _do_paint_rgb32(self, img_data, x : int, y : int, width : int, height : int, rowstride : int, options):
        if self._alpha_enabled:
            cformat = cairo.FORMAT_ARGB32
        else:
            cformat = cairo.FORMAT_RGB24
        return self._do_paint_rgb(cformat, True, img_data, x, y, width, height, rowstride, options)

    def _do_paint_rgb(self, *args):
        raise NotImplementedError()


    def get_encoding_properties(self):
        props = WindowBackingBase.get_encoding_properties(self)
        if SCROLL_ENCODING:
            props["encoding.scrolling"] = True
        return props


    def paint_scroll(self, img_data, _options, callbacks):
        self.idle_add(self.do_paint_scroll, img_data, callbacks)

    def do_paint_scroll(self, scrolls, callbacks):
        old_backing = self._backing
        gc = self.create_surface()
        if not gc:
            fire_paint_callbacks(callbacks, False, message="no context")
            return
        gc.set_operator(cairo.OPERATOR_SOURCE)
        for sx,sy,sw,sh,xdelta,ydelta in scrolls:
            gc.set_source_surface(old_backing, xdelta, ydelta)
            x = sx+xdelta
            y = sy+ydelta
            gc.rectangle(x, y, sw, sh)
            gc.fill()
            if self.paint_box_line_width>0:
                self.cairo_paint_box(gc, "scroll", x, y, sw, sh)
        del gc
        self._backing.flush()
        fire_paint_callbacks(callbacks)


    def nasty_rgb_via_png_paint(self, cairo_format, has_alpha : bool, img_data,
                                x : int, y : int, width : int, height : int, rowstride : int, rgb_format):
        log.warn("nasty_rgb_via_png_paint%s",
                 (cairo_format, has_alpha, len(img_data), x, y, width, height, rowstride, rgb_format))
        #PIL fallback
        from PIL import Image
        if has_alpha:
            oformat = "RGBA"
        else:
            oformat = "RGB"
        #use frombytes rather than frombuffer to be compatible with python3 new-style buffers
        #this is slower, but since this codepath is already dreadfully slow, we don't care
        bdata = memoryview_to_bytes(img_data)
        src_format = rgb_format.replace("X", "A")
        try:
            img = Image.frombytes(oformat, (width,height), bdata, "raw", src_format, rowstride, 1)
        except ValueError as e:
            log("PIL Image frombytes:", exc_info=True)
            raise Exception("failed to parse raw %s data as %s to %s: %s" % (
                rgb_format, src_format, oformat, e)) from None
        #This is insane, the code below should work, but it doesn't:
        # img_data = bytearray(img.tostring('raw', oformat, 0, 1))
        # pixbuf = new_from_data(img_data, COLORSPACE_RGB, True, 8, width, height, rowstride)
        # success = self.cairo_paint_pixbuf(pixbuf, x, y)
        #So we still rountrip via PNG:
        from io import BytesIO
        png = BytesIO()
        img.save(png, format="PNG")
        reader = BytesIO(png.getvalue())
        png.close()
        img = cairo.ImageSurface.create_from_png(reader)
        self.cairo_paint_surface(img, x, y, {})
        return True


    def cairo_draw(self, context):
        log("cairo_draw: size=%s, render-size=%s, offsets=%s, pointer_overlay=%s",
            self.size, self.render_size, self.offsets, self.pointer_overlay)
        if self._backing is None:
            return
        #try:
        #    log("clip rectangles=%s", context.copy_clip_rectangle_list())
        #except:
        #    log.error("clip:", exc_info=True)
        ww, wh = self.render_size
        w, h = self.size
        if ww==0 or w==0 or wh==0 or h==0:
            return
        x, y = self.offsets[:2]

        setup_cairo_context(context, ww, wh, w, h, x, y)
        context.set_source_surface(self._backing, 0, 0)
        context.paint()
        if self.pointer_overlay and self.cursor_data:
            px, py, _size, start_time = self.pointer_overlay[2:]
            spx = round(w*px/ww)
            spy = round(h*py/wh)
            cairo_paint_pointer_overlay(context, self.cursor_data, x+spx, y+spy, start_time)
