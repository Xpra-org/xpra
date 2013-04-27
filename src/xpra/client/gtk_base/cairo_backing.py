# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pygtk3 vs pygtk2 (sigh)
from xpra.gtk_common.gobject_compat import import_gdk, import_gobject
gdk = import_gdk()
gobject = import_gobject()
import cairo

from xpra.log import Logger
log = Logger()

from xpra.client.gtk_base.window_backing_base import WindowBacking, fire_paint_callbacks, DRAW_DEBUG

"""
An area we draw onto with cairo
This must be used with gtk3 since gtk3 no longer supports gdk pixmaps

/RANT: ideally we would want to use pycairo's create_for_data method:
#surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, width, height)
but this is disabled in most cases, or does not accept our rowstride, so we cannot use it.
Instead we have to use PIL to convert via a PNG!
This is a complete waste of CPU! Please complain to pycairo.
"""
class CairoBacking(WindowBacking):
    def __init__(self, wid, w, h):
        WindowBacking.__init__(self, wid)

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
        WindowBacking.close(self)
        self._backing.finish()

    def paint_png(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        try:
            from io import BytesIO          #@Reimport
            import sys
            if sys.version>='3':
                data = bytearray(img_data.encode("latin1"))
            else:
                try:
                    data = bytearray(img_data)
                except:
                    data = str(img_data)
            buf = BytesIO(data)
        except ImportError:
            from StringIO import StringIO   #@Reimport
            buf = StringIO(img_data)
        surf = cairo.ImageSurface.create_from_png(buf)
        gc = cairo.Context(self._backing)
        gc.set_source_surface(surf)
        gc.paint()
        surf.finish()
        fire_paint_callbacks(callbacks, True)
        return  False

    def paint_pil_image(self, pil_image, width, height, rowstride, options, callbacks):
        try:
            from io import BytesIO
            buf = BytesIO()
        except ImportError:
            from StringIO import StringIO   #@Reimport
            buf = StringIO()
        pil_image.save(buf, format="PNG")
        png_data = buf.getvalue()
        buf.close()
        gobject.idle_add(self.paint_png, png_data, 0, 0, width, height, rowstride, options, callbacks)

    def do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        if DRAW_DEBUG:
            log.info("cairo_paint_rgb24(..,%s,%s,%s,%s,%s,%s,%s)", x, y, width, height, rowstride, options, callbacks)
        gc = cairo.Context(self._backing)
        if rowstride==0:
            rowstride = width*3
        surf = cairo.ImageSurface.create_for_data(img_data, cairo.FORMAT_RGB24, width, height, rowstride)
        gc.set_source_surface(surf)
        gc.paint()
        surf.finish()
        fire_paint_callbacks(callbacks, True)
        del img_data
        return  False
