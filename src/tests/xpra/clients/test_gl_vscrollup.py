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


class GLWindowAnim(object):

    def __init__(self, client, wid, W=630, H=480):
        self.wid = wid
        self.W = W
        self.H = H
        self.window = GLClientWindow(client, None, 1, 10, 10, W, H, W, H, typedict({}), False, typedict({}), 0, None)
        self.window.show()
        self.paint_rect(0, 0, W, H, chr(255)*4*W*H)
        self.paint_rect(W//2-16, H//2-16, 32, 32, chr(0)*4*32*32)

    def scrollup(self):
        #scroll one line up:
        ydelta = 1
        scrolls = (0, ydelta, self.W, self.H-ydelta, -ydelta),
        self.window.draw_region(0, 0, self.W, self.H, "scroll", scrolls, self.W*4, 0, typedict({"flush" : 1}), [])
        dots = []
        for _ in range(self.W):
            CB = 0xFF << ((self.wid % 4) * 8)
            v = int(time.time()*10000)
            c = struct.pack("@I", v & 0xFFFFFFFF & ~CB)
            dots.append(c)
        img_data = b"".join(dots)
        self.paint_rect(0, self.H-ydelta*2, self.W, ydelta, img_data)
        return True

    def paint_rect(self, x=200, y=200, w=32, h=32, img_data="", options={}):
        self.window.draw_region(x, y, w, h, "rgb32", img_data, w*4, 0, typedict(options), [])


def main():
    try:
        import sys
        N = int(sys.argv[1])
    except:
        N = 1
    client = FakeGTKClient()
    for wid in range(N):
        anim = GLWindowAnim(client, wid)
        glib.timeout_add(20, anim.scrollup)
    try:
        gtk_main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
