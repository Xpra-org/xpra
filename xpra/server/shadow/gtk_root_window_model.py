# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import monotonic_time
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.gtk_common.gtk_util import get_pixbuf_from_window, pixbuf_save_to_memory
from xpra.log import Logger

log = Logger("shadow")


def get_rgb_rawdata(window, x, y, width, height):
    """
        Extracts pixels from the given pixmap
    """
    start = monotonic_time()
    pixmap_w, pixmap_h = window.get_geometry()[2:4]
    # Just in case we somehow end up with damage larger than the pixmap,
    # we don't want to start requesting random chunks of memory (this
    # could happen if a window is resized but we don't throw away our
    # existing damage map):
    assert x >= 0
    assert y >= 0
    if x + width > pixmap_w:
        width = pixmap_w - x
    if y + height > pixmap_h:
        height = pixmap_h - y
    if width <= 0 or height <= 0:
        return None
    pixbuf = get_pixbuf_from_window(window, x, y, width, height)
    log("get_rgb_rawdata(..) pixbuf.get_from_drawable took %s ms", int(1000*(monotonic_time()-start)))
    raw_data = pixbuf.get_pixels()
    rowstride = pixbuf.get_rowstride()
    return (x, y, width, height, raw_data, "RGB", 24, rowstride, 3)

def take_png_screenshot(window):
    log("grabbing screenshot")
    w,h = window.get_geometry()[2:4]
    pixbuf = get_pixbuf_from_window(window, 0, 0, w, h)
    data = pixbuf_save_to_memory(pixbuf, "png")
    rowstride = w*3
    if not pixbuf:
        return None
    return w, h, "png", rowstride, data


class GTKImageCapture(object):
    def __init__(self, window):
        self.window = window

    def __repr__(self):
        return "GTKImageCapture(%s)" % self.window

    def clean(self):
        pass

    def refresh(self):
        return True

    def get_image(self, x, y, width, height):
        attrs = get_rgb_rawdata(self.window, x, y, width, height)
        if not attrs:
            return None
        return ImageWrapper(*attrs)

    def take_screenshot(self):
        return take_png_screenshot(self.window)

def main(filename):
    from xpra.gtk_common.gtk_util import get_default_root_window
    root = get_default_root_window()
    data = take_png_screenshot(root)[-1]
    with open(filename, "wb") as f:
        f.write(data)
    return 0

if __name__ == "__main__":
    import sys
    if len(sys.argv)!=2:
        print("usage: %s filename.png" % sys.argv[0])
        v = 1
    else:
        v = main(sys.argv[1])
    sys.exit(v)
