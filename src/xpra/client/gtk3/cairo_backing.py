# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo
from gi.repository import GLib              #@UnresolvedImport
from gi.repository import GdkPixbuf         #@UnresolvedImport

from xpra.util import envbool
from xpra.client.gtk_base.cairo_backing_base import CairoBackingBase, FORMATS

from xpra.log import Logger
log = Logger("paint", "cairo")

try:
    from xpra.client.gtk3.cairo_workaround import set_image_surface_data    #@UnresolvedImport
except ImportError as e:
    log.warn("Warning: failed to load the gtk3 cairo workaround:")
    log.warn(" %s", e)
    log.warn(" rendering will be slow!")
    del e
    set_image_surface_data = None


CAIRO_USE_PIXBUF = envbool("XPRA_CAIRO_USE_PIXBUF", False)


"""
An area we draw onto with cairo
This must be used with gtk3 since gtk3 no longer supports gdk pixmaps

/RANT: ideally we would want to use pycairo's create_for_data method:
#surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, width, height)
but this is disabled in most cases, or does not accept our rowstride, so we cannot use it.
Instead we have to use PIL to convert via a PNG or Pixbuf!
"""
class CairoBacking(CairoBackingBase):

    RGB_MODES = ["BGRA", "BGRX", "RGBA", "RGBX", "BGR", "RGB"]

    def __repr__(self):
        return "gtk3.CairoBacking(%s)" % self._backing

    def _do_paint_rgb(self, cairo_format, has_alpha, img_data, x, y, width, height, rowstride, options):
        """ must be called from UI thread """
        log("cairo._do_paint_rgb(%s, %s, %s %s, %s, %s, %s, %s, %s, %s) set_image_surface_data=%s, use pixbuf=%s", FORMATS.get(cairo_format, cairo_format), has_alpha, len(img_data), type(img_data), x, y, width, height, rowstride, options, set_image_surface_data, CAIRO_USE_PIXBUF)
        rgb_format = options.strget(b"rgb_format", "RGB")
        if set_image_surface_data and not CAIRO_USE_PIXBUF:
            if (cairo_format==cairo.FORMAT_RGB24 and rgb_format in ("RGB", "BGR")) or \
                (cairo_format==cairo.FORMAT_ARGB32 and rgb_format in ("BGRX", "BGRA")):
                img_surface = cairo.ImageSurface(cairo_format, width, height)
                set_image_surface_data(img_surface, rgb_format, img_data, width, height, rowstride)
                self.cairo_paint_surface(img_surface, x, y, options)
                return True

        if rgb_format in ("RGB", "RGBA", "RGBX"):
            data = GLib.Bytes(img_data)
            pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB, has_alpha, 8, width, height, rowstride)
            self.cairo_paint_pixbuf(pixbuf, x, y, options)
            return True

        img_data = memoryview(img_data)
        self.nasty_rgb_via_png_paint(cairo_format, has_alpha, img_data, x, y, width, height, rowstride, rgb_format)
        return True
