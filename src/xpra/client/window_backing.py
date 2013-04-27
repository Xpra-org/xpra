# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gobject_compat import is_gtk3
import os

from xpra.log import Logger
log = Logger()


#pretend to draw the windows, but don't actually do anything
USE_FAKE_BACKING = os.environ.get("XPRA_USE_FAKE_BACKING", "0")=="1"
#just for testing the CairoBacking with gtk2
USE_CAIRO = os.environ.get("XPRA_USE_CAIRO_BACKING", "0")=="1"
#logging in the draw path is expensive:
DRAW_DEBUG = os.environ.get("XPRA_DRAW_DEBUG", "0")=="1"


if USE_FAKE_BACKING:
    from xpra.client.fake_window_backing import FakeBacking
    BACKING_CLASS = FakeBacking
elif is_gtk3() or USE_CAIRO:
    from xpra.client.gtk_base.cairo_backing import CairoBacking
    BACKING_CLASS = CairoBacking
else:
    from xpra.client.gtk2.pixmap_backing import PixmapBacking
    BACKING_CLASS = PixmapBacking


def new_backing(wid, w, h, backing, mmap_enabled, mmap):
    return make_new_backing(BACKING_CLASS, wid, w, h, backing, mmap_enabled, mmap)

def make_new_backing(backing_class, wid, w, h, backing, mmap_enabled, mmap):
    w = max(1, w)
    h = max(1, h)
    lock = None
    if backing:
        lock = backing._video_decoder_lock
    try:
        if lock:
            lock.acquire()
        if backing is None:
            backing = backing_class(wid, w, h)
            if mmap_enabled:
                backing.enable_mmap(mmap)
        backing.init(w, h)
    finally:
        if lock:
            lock.release()
    return backing
