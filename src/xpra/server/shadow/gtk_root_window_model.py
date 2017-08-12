# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk

from xpra.log import Logger
log = Logger("shadow")

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.gtk_common.pixbuf_to_rgb import get_rgb_rawdata
from xpra.server.shadow.root_window_model import RootWindowModel


class GTKRootWindowModel(RootWindowModel):

    def __repr__(self):
        return "GTKRootWindowModel(%s)" % self.window

    def get_image(self, x, y, width, height):
        v = get_rgb_rawdata(self.window, x, y, width, height)
        if v is None:
            return None
        return ImageWrapper(*v)

    def take_screenshot(self):
        log("grabbing screenshot")
        w,h = self.window.get_size()
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, w, h)
        pixbuf = pixbuf.get_from_drawable(self.window, self.window.get_colormap(), 0, 0, 0, 0, w, h)
        def save_to_memory(data, buf):
            buf.append(data)
        buf = []
        pixbuf.save_to_callback(save_to_memory, "png", {}, buf)
        rowstride = w*3
        return w, h, "png", rowstride, "".join(buf)
