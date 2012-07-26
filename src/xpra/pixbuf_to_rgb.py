# coding=utf8
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk
gtk.gdk.threads_init()
import time

from wimpiggy.log import Logger
log = Logger()

def get_rgb_rawdata(damage_time, process_damage_time, wid, pixmap, x, y, width, height, encoding, sequence, options):
    """
        Extracts pixels from the given pixmap
    """
    start = time.time()
    pixmap_w, pixmap_h = pixmap.get_size()
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
    pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, width, height)
    colormap = pixmap.get_colormap()
    if not colormap:
        log.error("get_rgb_rawdata(..) no colormap for RGB pixbuf %sx%s", width, height)
        return None
    pixbuf.get_from_drawable(pixmap, colormap, x, y, 0, 0, width, height)
    log("get_rgb_rawdata(..) pixbuf.get_from_drawable took %s ms", int(1000*(time.time()-start)))
    raw_data = pixbuf.get_pixels()
    rowstride = pixbuf.get_rowstride()
    return (damage_time, process_damage_time, wid, x, y, width, height, encoding, raw_data, rowstride, sequence, options)
