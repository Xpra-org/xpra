# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gdk, import_gobject, import_pixbufloader, import_cairo, import_glib
gdk             = import_gdk()
gobject         = import_gobject()
cairo           = import_cairo()
PixbufLoader    = import_pixbufloader()
glib            = import_glib()

from xpra.gtk_common.gtk_util import cairo_set_source_pixbuf, gdk_cairo_context
from xpra.client.paint_colors import get_paint_box_color
from xpra.client.window_backing_base import WindowBackingBase
from xpra.client.gtk_base.gtk_window_backing_base import GTK_ALPHA_SUPPORTED
from xpra.codecs.loader import get_codec
from xpra.os_util import BytesIOClass, memoryview_to_bytes, strtobytes

from xpra.log import Logger
log = Logger("paint", "cairo")


FORMATS = {-1   : "INVALID"}
for x in (f for f in dir(cairo) if f.startswith("FORMAT_")):
    FORMATS[getattr(cairo, x)] = x.replace("FORMAT_", "")


"""
Superclass for gtk2 and gtk3 cairo implementations.
"""
class CairoBackingBase(WindowBackingBase):

    HAS_ALPHA = GTK_ALPHA_SUPPORTED

    def __init__(self, wid, window_alpha, _pixel_depth=0):
        WindowBackingBase.__init__(self, wid, window_alpha and GTK_ALPHA_SUPPORTED)
        self.idle_add = glib.idle_add

    def init(self, ww, wh, w, h):
        self.size = w, h
        self.render_size = ww, wh
        old_backing = self._backing
        #should we honour self.depth here?
        self._backing = None
        if w==0 or h==0:
            #this can happen during cleanup
            return
        self._backing = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(self._backing)
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        if old_backing is not None:
            # Really we should respect bit-gravity here but... meh.
            old_w = old_backing.get_width()
            old_h = old_backing.get_height()
            cr.set_operator(cairo.OPERATOR_SOURCE)
            if w>old_w and h>old_h:
                #both width and height are bigger:
                cr.rectangle(old_w, 0, w-old_w, h)
                cr.fill()
                cr.new_path()
                cr.rectangle(0, old_h, old_w, h-old_h)
                cr.fill()
            elif w>old_w:
                #enlarged in width only
                cr.rectangle(old_w, 0, w-old_w, h)
                cr.fill()
            if h>old_h:
                #enlarged in height only
                cr.rectangle(0, old_h, w, h-old_h)
                cr.fill()
            #cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.set_source_surface(old_backing, 0, 0)
            cr.paint()
            #old_backing.finish()

    def close(self):
        if self._backing:
            self._backing.finish()
        WindowBackingBase.close(self)


    def cairo_paint_pixbuf(self, pixbuf, x, y, options):
        """ must be called from UI thread """
        log("source pixbuf: %s", pixbuf)
        w, h = pixbuf.get_width(), pixbuf.get_height()
        self.cairo_paint_from_source(cairo_set_source_pixbuf, pixbuf, x, y, w, h, options)

    def cairo_paint_surface(self, img_surface, x, y, options={}):
        w, h = img_surface.get_width(), img_surface.get_height()
        log("source image surface: %s", (img_surface.get_format(), w, h, img_surface.get_stride(), img_surface.get_content(), ))
        def set_source_surface(gc, surface, sx, sy):
            gc.set_source_surface(surface, sx, sy)
        self.cairo_paint_from_source(set_source_surface, img_surface, x, y, w, h, options)

    def cairo_paint_from_source(self, set_source_fn, source, x, y, w, h, options):
        """ must be called from UI thread """
        log("cairo_paint_surface(%s, %s, %s, %s, %s, %s, %s) backing=%s, paint box line width=%i", set_source_fn, source, x, y, w, h, options, self._backing, self.paint_box_line_width)
        gc = gdk_cairo_context(cairo.Context(self._backing))
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
        if self.paint_box_line_width and options:
            gc.restore()
            encoding = options.get("encoding")
            if encoding:
                color = get_paint_box_color(encoding)
                gc.set_line_width(self.paint_box_line_width)
                gc.set_source_rgba(*color)
                gc.rectangle(x, y, w, h)
                gc.stroke()


    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options):
        return self._do_paint_rgb(cairo.FORMAT_RGB24, False, img_data, x, y, width, height, rowstride, options)

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options):
        return self._do_paint_rgb(cairo.FORMAT_ARGB32, True, img_data, x, y, width, height, rowstride, options)

    def _do_paint_rgb(self, *args):
        raise NotImplementedError()


    def nasty_rgb_via_png_paint(self, cairo_format, has_alpha, img_data, x, y, width, height, rowstride, rgb_format):
        log.warn("nasty_rgb_via_png_paint%s", (cairo_format, has_alpha, len(img_data), x, y, width, height, rowstride, rgb_format))
        #PIL fallback
        PIL = get_codec("PIL")
        if has_alpha:
            oformat = "RGBA"
        else:
            oformat = "RGB"
        #use frombytes rather than frombuffer to be compatible with python3 new-style buffers
        #this is slower, but since this codepath is already dreadfully slow, we don't care
        bdata = strtobytes(memoryview_to_bytes(img_data))
        src_format = rgb_format.replace("X", "A")
        try:
            img = PIL.Image.frombytes(oformat, (width,height), bdata, "raw", src_format, rowstride, 1)
        except ValueError as e:
            log("PIL Image frombytes:", exc_info=True)
            raise Exception("failed to parse raw %s data as %s to %s: %s" % (rgb_format, src_format, oformat, e))
        #This is insane, the code below should work, but it doesn't:
        # img_data = bytearray(img.tostring('raw', oformat, 0, 1))
        # pixbuf = pixbuf_new_from_data(img_data, COLORSPACE_RGB, True, 8, width, height, rowstride)
        # success = self.cairo_paint_pixbuf(pixbuf, x, y)
        #So we still rountrip via PNG:
        png = BytesIOClass()
        img.save(png, format="PNG")
        reader = BytesIOClass(png.getvalue())
        png.close()
        img = cairo.ImageSurface.create_from_png(reader)
        self.cairo_paint_surface(img, x, y)
        return True


    def cairo_draw(self, context):
        log("cairo_draw: size=%s, render-size=%s, offsets=%s", self.size, self.render_size, self.offsets)
        if self._backing is None:
            return False
        #try:
        #    log("clip rectangles=%s", context.copy_clip_rectangle_list())
        #except:
        #    log.error("clip:", exc_info=True)
        try:
            if self.render_size!=self.size:
                ww, wh = self.render_size
                w, h = self.size
                context.scale(float(ww)/w, float(wh)/h)
            x, y = self.offsets[:2]
            if x!=0 or y!=0:
                context.translate(x, y)
            context.set_source_surface(self._backing, 0, 0)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
            return True
        except KeyboardInterrupt:
            raise
        except:
            log.error("cairo_draw(%s)", context, exc_info=True)
            return False
