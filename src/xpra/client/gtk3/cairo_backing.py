# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo
from gi.repository import GObject           #@UnresolvedImport
from gi.repository import GdkPixbuf         #@UnresolvedImport

from xpra.client.gtk_base.cairo_backing_base import CairoBackingBase
from xpra.os_util import BytesIOClass
from xpra.client.gtk_base.gtk_window_backing_base import GTKWindowBacking
from xpra.client.window_backing_base import fire_paint_callbacks
try:
    from xpra.client.gtk3.cairo_workaround import set_image_surface_data    #@UnresolvedImport
except:
    set_image_surface_data = None

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
class CairoBacking(CairoBackingBase):

    RGB_MODES = ["ARGB", "XRGB", "RGBA", "RGBX", "RGB"]


    def __repr__(self):
        return "gtk3.CairoBacking(%s)" % self._backing


    def paint_image(self, coding, img_data, x, y, width, height, options, callbacks):
        log("cairo.paint_image(%s, %s bytes,%s,%s,%s,%s,%s,%s) alpha_enabled=%s", coding, len(img_data), x, y, width, height, options, callbacks, self._alpha_enabled)
        #catch PNG and jpeg we can handle via cairo or pixbufloader respectively
        #(both of which need to run from the UI thread)
        if coding.startswith("png") or coding=="jpeg":
            def ui_paint_image():
                if not self._backing:
                    fire_paint_callbacks(callbacks, False)
                    return
                try:
                    if coding.startswith("png"):
                        reader = BytesIOClass(img_data)
                        img = cairo.ImageSurface.create_from_png(reader)
                        success = self.cairo_paint_surface(img, x, y)
                    else:
                        assert coding=="jpeg"
                        pbl = GdkPixbuf.PixbufLoader()
                        pbl.write(img_data)
                        pbl.close()
                        pixbuf = pbl.get_pixbuf()
                        del pbl
                        success = self.cairo_paint_pixbuf(pixbuf, x, y)
                except:
                    log.error("cairo error during paint", exc_info=True)
                    success = False
                fire_paint_callbacks(callbacks, success)
            GObject.idle_add(ui_paint_image)
            return
        #this will end up calling do_paint_rgb24 after converting the pixels to RGB
        GTKWindowBacking.paint_image(self, coding, img_data, x, y, width, height, options, callbacks)


    def _do_paint_rgb(self, cairo_format, has_alpha, img_data, x, y, width, height, rowstride, options):
        """ must be called from UI thread """
        log("cairo._do_paint_rgb(%s, %s, %s bytes,%s,%s,%s,%s,%s,%s)", cairo_format, has_alpha, len(img_data), x, y, width, height, rowstride, options)
        rgb_format = options.strget("rgb_format", "RGB")
        #this format we can handle with the workaround:
        if format==cairo.FORMAT_RGB24 and rgb_format=="RGB" and set_image_surface_data:
            img_surface = cairo.ImageSurface(cairo_format, width, height)
            set_image_surface_data(img_surface, rgb_format, img_data, width, height, rowstride)
            return self.cairo_paint_surface(img_surface, x, y)

        self.nasty_rgb_via_png_paint(cairo_format, has_alpha, img_data, x, y, width, height, rowstride, rgb_format)
        return True
