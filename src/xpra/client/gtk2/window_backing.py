# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gtk import gdk #@UnresolvedImport
import glib         #@UnresolvedImport

from xpra.util import envbool
from xpra.client.window_backing_base import WindowBackingBase
from xpra.client.window_backing_base import fire_paint_callbacks
from xpra.client.gtk_base.gtk_window_backing_base import GTK_ALPHA_SUPPORTED
from xpra.codecs.loader import has_codec
from xpra.log import Logger

log = Logger("paint")

USE_PIL = envbool("XPRA_USE_PIL", True)


"""
This is the gtk2 version.
(works much better than gtk3!)
Superclass for PixmapBacking and GLBacking
"""
class GTK2WindowBacking(WindowBackingBase):

    HAS_ALPHA = GTK_ALPHA_SUPPORTED

    def __init__(self, wid, window_alpha, _pixel_depth=0):
        WindowBackingBase.__init__(self, wid, window_alpha and self.HAS_ALPHA)
        self.idle_add = glib.idle_add

    def init(self, *args):
        raise Exception("override me!")


    def paint_image(self, coding, img_data, x, y, width, height, options, callbacks):
        """ can be called from any thread """
        if USE_PIL and has_codec("dec_pillow"):
            return WindowBackingBase.paint_image(self, coding, img_data, x, y, width, height, options, callbacks)
        #gdk needs UI thread:
        self.idle_add(self.paint_pixbuf_gdk, coding, img_data, x, y, width, height, options, callbacks)
        return  False

    def do_draw_region(self, x, y, width, height, coding, img_data, _rowstride, options, callbacks): #pylint: disable=arguments-differ
        """ called as last resort when PIL is not available"""
        self.idle_add(self.paint_pixbuf_gdk, coding, img_data, x, y, width, height, options, callbacks)


    def paint_pixbuf_gdk(self, coding, img_data, x, y, width, height, options, callbacks):
        """ must be called from UI thread """
        if coding.startswith("png"):
            coding = "png"
        else:
            assert coding=="jpeg"
        loader = gdk.PixbufLoader(coding)
        loader.write(img_data, len(img_data))
        loader.close()
        pixbuf = loader.get_pixbuf()
        if not pixbuf:
            msg = "failed to load a pixbuf from %i bytes of %s data" % (len(img_data), coding)
            log.error("Error: %s", msg)
            fire_paint_callbacks(callbacks, False, msg)
            return  False
        raw_data = pixbuf.get_pixels()
        rowstride = pixbuf.get_rowstride()
        img_data = self.process_delta(raw_data, width, height, rowstride, options)
        n = pixbuf.get_n_channels()
        if n==3:
            self._do_paint_rgb24(img_data, x, y, width, height, rowstride, options)
        else:
            assert n==4, "invalid number of channels: %s" % n
            self._do_paint_rgb32(img_data, x, y, width, height, rowstride, options)
        fire_paint_callbacks(callbacks, True)
        return False

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options):
        raise NotImplementedError()

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options):
        raise NotImplementedError()
