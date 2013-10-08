# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo

from xpra.log import Logger
log = Logger()

from xpra.client.gtk_base.gtk_window_backing_base import GTKWindowBacking
from xpra.client.window_backing_base import fire_paint_callbacks, DRAW_DEBUG
from xpra.os_util import BytesIOClass, data_to_buffer
from xpra.codecs.loader import get_codec


"""
An area we draw onto with cairo
This must be used with gtk3 since gtk3 no longer supports gdk pixmaps

/RANT: ideally we would want to use pycairo's create_for_data method:
#surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, width, height)
but this is disabled in most cases, or does not accept our rowstride, so we cannot use it.
Instead we have to use PIL to convert via a PNG!
This is a complete waste of CPU! Please complain to pycairo.
"""
class CairoBacking(GTKWindowBacking):
    def __init__(self, wid, w, h, has_alpha):
        GTKWindowBacking.__init__(self, wid)

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
        GTKWindowBacking.close(self)
        self._backing.finish()

    def paint_png(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        if self._backing is None:
            fire_paint_callbacks(callbacks, False)
            return
        buf = data_to_buffer(img_data)
        self.do_paint_png(buf, x, y, width, height, rowstride, options, callbacks)

    def do_paint_png(self, buf, x, y, width, height, rowstride, options, callbacks):
        surf = cairo.ImageSurface.create_from_png(buf)
        gc = cairo.Context(self._backing)
        gc.set_source_surface(surf)
        gc.paint()
        surf.finish()
        fire_paint_callbacks(callbacks, True)

    def paint_pil_image(self, pil_image, width, height, rowstride, options, callbacks):
        buf = BytesIOClass()
        pil_image.save(buf, format="PNG")
        png_data = buf.getvalue()
        buf.close()
        self.idle_add(self.paint_png, png_data, 0, 0, width, height, rowstride, options, callbacks)

    def do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        if DRAW_DEBUG:
            log.info("cairo_paint_rgb24(..,%s,%s,%s,%s,%s,%s,%s)", x, y, width, height, rowstride, options, callbacks)
        if self._backing is None:
            fire_paint_callbacks(callbacks, False)
            return  False
        PIL = get_codec("PIL")
        assert PIL, "cannot paint without PIL!"
        if rowstride==0:
            rowstride = width * 3
        im = PIL.Image.frombuffer("RGB", (width, height), img_data, "raw", "RGB", rowstride)
        buf = BytesIOClass()
        im.save(buf, "PNG")
        data = buf.getvalue()
        buf.close()
        img_data = BytesIOClass(data)
        self.do_paint_png(img_data, x, y, width, height, rowstride, options, callbacks)
        return  False


    def cairo_draw(self, context):
        if self._backing is None:
            return
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
