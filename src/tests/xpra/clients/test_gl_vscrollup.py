#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import struct
from xpra.log import Logger
log = Logger()

import glib

from xpra.util import typedict
from xpra.client.gl.gtk2.gl_client_window import GLClientWindow
from tests.xpra.clients.fake_gtk_client import FakeGTKClient, gtk_main
from xpra.codecs.loader import load_codecs

load_codecs(encoders=False, decoders=True, csc=False)


def main():
    W = 640
    H = 480
    client = FakeGTKClient()
    window = GLClientWindow(client, None, 1, 10, 10, W, H, W, H, typedict({}), False, typedict({}), 0, None)
    window.show()
    def paint_rect(x=200, y=200, w=32, h=32, img_data="", options={}):
        #print("paint_rect%s" % ((x, y, w, h),))
        window.draw_region(x, y, w, h, "rgb32", img_data, w*4, 0, typedict(options), [])
    img_data = chr(255)*4*W*H
    glib.timeout_add(0, paint_rect, 0, 0, W, H, img_data)
    img_data = chr(0)*4*32*32
    glib.timeout_add(10, paint_rect, W//2-16, H//2-16, 32, 32, img_data)
    def scrollup():
        #scroll one line up:
        ydelta = 1
        scrolls = (0, ydelta, W, H-ydelta, -ydelta),
        window.draw_region(0, 0, W, H, "scroll", scrolls, W*4, 0, typedict({"flush" : 1}), [])
        dots = []
        for _ in range(W):
            c = struct.pack("@I", int(time.time()*1000) % 0xFFFFFFFF)
            dots.append(c)
        img_data = b"".join(dots)
        paint_rect(0, H-ydelta*2, W, ydelta, img_data)
        return True
    glib.timeout_add(20, scrollup)
    try:
        gtk_main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
