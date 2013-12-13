# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from gtk import gdk
import gobject
import os

from xpra.log import Logger
log = Logger()

from xpra.client.gtk_base.gtk_window_backing_base import GTKWindowBacking
from xpra.client.window_backing_base import fire_paint_callbacks
from xpra.codecs.loader import has_codec

#don't bother trying gtk2 transparency on on MS Windows (not supported):
#or on OSX (doesn't work)
HAS_RGBA = not sys.platform.startswith("win") and not sys.platform.startswith("darwin")
try:
    #we need argb to un-premultiply alpha:
    from xpra.codecs.argb.argb import unpremultiply_argb, unpremultiply_argb_in_place, byte_buffer_to_buffer   #@UnresolvedImport
except:
    log.warn("argb module is missing, cannot support alpha channels")
    unpremultiply_argb, unpremultiply_argb_in_place, byte_buffer_to_buffer  = None, None, None
    HAS_RGBA = False


"""
This is the gtk2 version.
(works much better than gtk3!)
Superclass for PixmapBacking and GLBacking
"""
class GTK2WindowBacking(GTKWindowBacking):

    def __init__(self, wid, w, h, has_alpha):
        GTKWindowBacking.__init__(self, wid)
        self._has_alpha = has_alpha and HAS_RGBA

    def init(self, w, h):
        raise Exception("override me!")


    def unpremultiply(self, img_data):
        if type(img_data)==str:
            #cannot do in-place:
            assert unpremultiply_argb is not None, "missing argb.unpremultiply_argb"
            return byte_buffer_to_buffer(unpremultiply_argb(img_data))
        #assume this is a writeable buffer (ie: ctypes from mmap):
        assert unpremultiply_argb is not None, "missing argb.unpremultiply_argb_in_place"
        unpremultiply_argb_in_place(img_data)
        return img_data

    def paint_image(self, coding, img_data, x, y, width, height, options, callbacks):
        """ can be called from any thread """
        use_PIL = has_codec("PIL") and os.environ.get("XPRA_USE_PIL", "1")=="1"
        if use_PIL:
            return GTKWindowBacking.paint_image(self, coding, img_data, x, y, width, height, options, callbacks)
        #gdk needs UI thread:
        gobject.idle_add(self.paint_pixbuf_gdk, coding, img_data, x, y, width, height, options, callbacks)
        return  False

    def paint_pixbuf_gdk(self, coding, img_data, x, y, width, height, options, callbacks):
        """ must be called from UI thread """
        loader = gdk.PixbufLoader(coding)
        loader.write(img_data, len(img_data))
        loader.close()
        pixbuf = loader.get_pixbuf()
        if not pixbuf:
            log.error("failed %s pixbuf=%s data len=%s" % (coding, pixbuf, len(img_data)))
            fire_paint_callbacks(callbacks, False)
            return  False
        raw_data = pixbuf.get_pixels()
        rowstride = pixbuf.get_rowstride()
        img_data = self.process_delta(raw_data, width, height, rowstride, options)
        self.do_paint_rgb24(img_data, x, y, width, height, rowstride, options, callbacks)
        return False
