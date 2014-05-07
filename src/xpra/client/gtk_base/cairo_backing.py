# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo

from xpra.gtk_common.gobject_compat import import_gdk, import_gobject, import_pixbufloader
gdk = import_gdk()
gobject = import_gobject()
PixbufLoader = import_pixbufloader()

from xpra.gtk_common.gtk_util import pixbuf_new_from_data, COLORSPACE_RGB
from xpra.client.gtk_base.gtk_window_backing_base import GTKWindowBacking
from xpra.client.window_backing_base import fire_paint_callbacks
from xpra.codecs.loader import get_codec
from xpra.os_util import builtins
_memoryview = builtins.__dict__.get("memoryview")


from xpra.log import Logger
log = Logger("paint", "cairo")



"""
An area we draw onto with cairo
This must be used with gtk3 since gtk3 no longer supports gdk pixmaps

/RANT: ideally we would want to use pycairo's create_for_data method:
#surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, width, height)
but this is disabled in most cases, or does not accept our rowstride, so we cannot use it.
Instead we have to use PIL to convert via a PNG or Pixbuf!
"""
class CairoBacking(GTKWindowBacking):

    def __init__(self, wid, w, h, has_alpha):
        GTKWindowBacking.__init__(self, wid)

    def __repr__(self):
        return "CairoBacking(%s)" % self._backing

    def init(self, w, h):
        old_backing = self._backing
        #should we honour self.depth here?
        self._backing = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(self._backing)
        if old_backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_surface(old_backing, 0, 0)
            cr.paint()
            old_w = old_backing.get_width()
            old_h = old_backing.get_height()
            cr.move_to(old_w, 0)
            cr.line_to(w, 0)
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.line_to(0, old_h)
            cr.line_to(old_w, old_h)
            cr.close_path()
            old_backing.finish()
        else:
            cr.rectangle(0, 0, w, h)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()

    def close(self):
        if self._backing:
            self._backing.finish()
        GTKWindowBacking.close(self)


    def paint_image(self, coding, img_data, x, y, width, height, options, callbacks):
        log("cairo.paint_image(%s, %s bytes,%s,%s,%s,%s,%s,%s)", coding, len(img_data), x, y, width, height, options, callbacks)
        if coding.startswith("png") or coding=="jpeg":
            def ui_paint_image():
                success = False
                if self._backing:
                    success = self.cairo_paint_image(img_data, x, y)
                fire_paint_callbacks(callbacks, success)
            gobject.idle_add(ui_paint_image)
            return
        #this will end up calling do_paint_rgb24 after converting the pixels to RGB
        GTKWindowBacking.paint_image(self, coding, img_data, x, y, width, height, options, callbacks)

    def cairo_paint_image(self, img_data, x, y):
        """ must be called from UI thread """
        log("cairo_paint_image(%s bytes, %s, %s) backing=%s", len(img_data), x, y, self._backing)
        #load into a pixbuf
        pbl = PixbufLoader()
        pbl.write(img_data)
        pbl.close()
        pixbuf = pbl.get_pixbuf()
        del pbl
        return self.cairo_paint_pixbuf(pixbuf, x, y)

    def cairo_paint_pixbuf(self, pixbuf, x, y):
        """ must be called from UI thread """
        log("cairo_paint_pixbuf(%s, %s, %s) backing=%s", pixbuf, x, y, self._backing)
        #now use it to paint:
        gc = cairo.Context(self._backing)
        gdk.cairo_set_source_pixbuf(gc, pixbuf, x, y)
        gc.paint()
        return True

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        log("_do_paint_rgb24")
        return self._do_paint_rgb(False, img_data, x, y, width, height, rowstride, options, callbacks)

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options, callbacks):
        log("_do_paint_rgb32")
        return self._do_paint_rgb(True, img_data, x, y, width, height, rowstride, options, callbacks)

    def _do_paint_rgb(self, has_alpha, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        log("cairo._do_paint_rgb(%s, %s bytes,%s,%s,%s,%s,%s,%s,%s)", has_alpha, len(img_data), x, y, width, height, rowstride, options, callbacks)
        rgb_format = options.strget("rgb_format", "RGB")
        if rgb_format in ("RGBX", "RGBA"):
            rgba = self.unpremultiply(img_data)
            pixbuf = pixbuf_new_from_data(rgba, COLORSPACE_RGB, has_alpha, 8, width, height, rowstride, None, None)
            return self.cairo_paint_pixbuf(pixbuf, x, y)
        PIL = get_codec("PIL")
        assert PIL, "cannot paint without PIL!"
        if _memoryview and isinstance(img_data, _memoryview):
            #PIL can't use memory view directly
            img_data = bytes(img_data)
        im = PIL.Image.frombuffer("RGB", (width, height), img_data, "raw", rgb_format, rowstride)
        im = im.convert("RGBX")
        data = im.tostring("raw", "RGBX", 0, 1)
        log.info("%s: %s bytes, now RGBX: %s bytes", rgb_format, len(img_data), len(data))
        pixbuf = pixbuf_new_from_data(data, COLORSPACE_RGB, False, 8, width, height, width*4, None, None)
        return self.cairo_paint_pixbuf(pixbuf, x, y)

    def cairo_draw(self, context):
        log("cairo_draw(%s) backing=%s", context, self._backing)
        if self._backing is None:
            return False
        try:
            context.set_source_surface(self._backing, 0, 0)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
            return True
        except KeyboardInterrupt:
            raise
        except:
            log.error("cairo_draw(%s)", context, exc_info=True)
            return False
