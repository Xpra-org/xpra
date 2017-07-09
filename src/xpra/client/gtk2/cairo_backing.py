# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo

from xpra.client.gtk_base.cairo_backing_base import CairoBackingBase
from xpra.gtk_common.gtk_util import pixbuf_new_from_data, COLORSPACE_RGB
from xpra.os_util import memoryview_to_bytes

from xpra.log import Logger
log = Logger("paint", "cairo")


"""
    With python2 / gtk2, we can create an ImageSurface using either:
    * cairo.ImageSurface.create_for_data
    * pixbuf_new_from_data
    Failing that, we use the horrible roundtrip via PNG using PIL.
"""
class CairoBacking(CairoBackingBase):

    #with gtk2 we can convert these directly to a cairo image surface:
    RGB_MODES = ["ARGB", "RGBA", "RGBX", "RGB"]


    def __repr__(self):
        return "gtk2.CairoBacking(%s)" % self._backing


    def _do_paint_rgb(self, cairo_format, has_alpha, img_data, x, y, width, height, rowstride, options):
        """ must be called from UI thread """
        log("cairo._do_paint_rgb(%s, %s, %s bytes,%s,%s,%s,%s,%s,%s)", cairo_format, has_alpha, len(img_data), x, y, width, height, rowstride, options)
        rgb_format = options.strget("rgb_format", "RGB")

        if rgb_format in ("ARGB", ):
            #the pixel format is also what cairo expects
            #maybe we should also check that the stride is acceptable for cairo?
            #cairo_stride = cairo.ImageSurface.format_stride_for_width(cairo_format, width)
            #log("cairo_stride=%s, stride=%s", cairo_stride, rowstride)
            pix_data = bytearray(img_data)
            img_surface = cairo.ImageSurface.create_for_data(pix_data, cairo_format, width, height, rowstride)
            self.cairo_paint_surface(img_surface, x, y, options)
            return True

        if rgb_format in ("RGBA", "RGBX", "RGB"):
            #with GTK2, we can use a pixbuf from RGB(A) pixels
            if rgb_format=="RGBA":
                #we have to unpremultiply for pixbuf!
                img_data = self.unpremultiply(img_data)
            #Pixbuf cannot use the memoryview directly:
            img_data = memoryview_to_bytes(img_data)
            pixbuf = pixbuf_new_from_data(img_data, COLORSPACE_RGB, has_alpha, 8, width, height, rowstride)
            self.cairo_paint_pixbuf(pixbuf, x, y, options)
            return True

        self.nasty_rgb_via_png_paint(cairo_format, has_alpha, img_data, x, y, width, height, rowstride, rgb_format)
        return True
