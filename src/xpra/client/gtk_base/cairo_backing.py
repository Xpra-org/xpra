# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo
import array

from xpra.client.gtk_base.gtk_window_backing_base import GTKWindowBacking
from xpra.client.window_backing_base import fire_paint_callbacks
from xpra.os_util import BytesIOClass
from xpra.codecs.loader import get_codec

from xpra.log import Logger
log = Logger("paint", "cairo")

from xpra.gtk_common.gobject_compat import is_gtk3, import_gdk, import_gobject
gdk = import_gdk()
gobject = import_gobject()
if is_gtk3():
    from gi.repository import GdkPixbuf     #@UnresolvedImport
    PixbufLoader = GdkPixbuf.PixbufLoader
else:
    from gtk.gdk import PixbufLoader


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
        if coding.startswith("png") or coding=="jpeg":
            gobject.idle_add(self.cairo_paint_image, img_data, x, y, callbacks)
            return
        #this will end up calling do_paint_rgb24 after converting the pixels to RGB
        GTKWindowBacking.paint_image(self, coding, img_data, x, y, width, height, options, callbacks)

    def cairo_paint_image(self, img_data, x, y, callbacks):
        """ must be called from UI thread """
        #load into a pixbuf
        pbl = PixbufLoader()
        pbl.write(img_data)
        pbl.close()
        pixbuf = pbl.get_pixbuf()
        del pbl
        self.cairo_paint_pixbuf(pixbuf, x, y, callbacks)

    def cairo_paint_pixbuf(self, pixbuf, x, y, callbacks):
        """ must be called from UI thread """
        if self._backing is None:
            fire_paint_callbacks(callbacks, False)
            return
        #now use it to paint:
        gc = cairo.Context(self._backing)
        gdk.cairo_set_source_pixbuf(gc, pixbuf, x, y)
        gc.paint()
        del pixbuf, gc
        fire_paint_callbacks(callbacks, True)


    def do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        log("cairo.do_paint_rgb24(..,%s,%s,%s,%s,%s,%s,%s)", x, y, width, height, rowstride, options, callbacks)
        if self._backing is None:
            fire_paint_callbacks(callbacks, False)
            return  False
        PIL = get_codec("PIL")
        assert PIL, "cannot paint without PIL!"
        if rowstride==0:
            rowstride = width * 3
        im = PIL.Image.frombuffer("RGB", (width, height), img_data, "raw", "RGB", rowstride)
        if is_gtk3():
            data = array.array('B', im.tostring())
            pixbuf = GdkPixbuf.Pixbuf.new_from_data(data, GdkPixbuf.Colorspace.RGB,
                                          True, 8, width, height, width * 4,
                                          None, None)
            self.cairo_paint_pixbuf(pixbuf, x, y, callbacks)
            return
        #roundtrip via PNG! (crappy cairo API)
        buf = BytesIOClass()
        im.save(buf, "PNG")
        data = buf.getvalue()
        buf.close()
        img_data = BytesIOClass(data)
        surf = cairo.ImageSurface.create_from_png(img_data)
        gc = cairo.Context(self._backing)
        gc.set_source_surface(surf, x, y)
        gc.paint()
        surf.finish()
        fire_paint_callbacks(callbacks, True)
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
