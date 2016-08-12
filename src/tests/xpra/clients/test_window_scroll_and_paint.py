#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
import math
from xpra.log import Logger
log = Logger()

import glib

from xpra.util import typedict
from tests.xpra.clients.fake_gtk_client import FakeGTKClient, gtk_main
from xpra.codecs.loader import load_codecs

load_codecs(encoders=False, decoders=True, csc=False)


class WindowAnim(object):

    def __init__(self, window_class, client, wid, W=630, H=480):
        self.wid = wid
        self.window = window_class(client, None, wid, 10, 10, W, H, W, H, typedict({}), False, typedict({}), 0, None)
        self.window.show()
        self.paint_rect(0, 0, W, H, chr(255)*4*W*H)

    def paint_crect(self, x=200, y=200, w=32, h=32, color=0x80808080):
        import struct
        c = struct.pack("@I", color & 0xFFFFFFFF)
        img_data = c*w*h
        self.window.draw_region(x, y, w, h, "rgb32", img_data, w*4, 0, typedict({}), [])

    def paint_rect(self, x=200, y=200, w=32, h=32, img_data=None, options={}):
        assert img_data
        self.window.draw_region(x, y, w, h, "rgb32", img_data, w*4, 0, typedict(options), [])

    def paint_png(self, x=256, y=256):
        W, H = self.window.get_size()
        img_data = binascii.unhexlify("89504e470d0a1a0a0000000d494844520000010000000100010300000066bc3a2500000003504c54"
                                      "45b5d0d0630416ea0000001f494441546881edc1010d000000c2a0f74f6d0e37a000000000000000"
                                      "00be0d210000019a60e1d50000000049454e44ae426082")
        self.window.draw_region((W-x)//2, (H-x)//2, x, y, "png", img_data, W*4, 0, typedict(), [])

    def paint_and_vscroll(self, ydelta=10):
        print("paint_and_scroll(%i)" % (ydelta))
        W, H = self.window.get_size()
        if ydelta>0:
            #scroll down, repaint the top:
            scrolls = (0, 0, W, H-ydelta, 0, ydelta),
            self.window.draw_region(0, 0, W, H, "scroll", scrolls, W*4, 0, typedict({"flush" : 1}), [])
            self.paint_crect(0, 0, W, ydelta, 0x80808080)
        else:
            #scroll up, repaint the bottom:
            scrolls = (0, -ydelta, W, H+ydelta, 0, ydelta),
            self.window.draw_region(0, 0, W, H, "scroll", scrolls, W*4, 0, typedict({"flush" : 1}), [])
            self.paint_crect(0, H-ydelta, W, -ydelta, 0xA0008020)

    def split_vscroll(self, i=1):
        W, H = self.window.get_size()
        scrolls = [
                   (0,      H//2,   W,      H//2-i,     0,  i),
                   (0,      i,      W,      H//2-i,     0,  -i),
                   ]
        self.window.draw_region(0, 0, W, H, "scroll", scrolls, W*4, 0, typedict({}), [])


def main():
    W = 640
    H = 480
    try:
        from xpra.client.gl.gtk2.gl_client_window import GLClientWindow
        window_class = GLClientWindow
    except Exception as e:
        print("no opengl window: %s" % e)
        from xpra.client.gtk2.border_client_window import BorderClientWindow
        window_class = BorderClientWindow
    client = FakeGTKClient()
    window = WindowAnim(window_class, client, 1)
    window.paint_png()
    for i in range(4):
        glib.timeout_add(500, window.paint_crect,               W//4*i + W//8, 100, 32, 32, 0x30*i)
    for i in range(50):
        glib.timeout_add(1000+i*20, window.paint_crect,         int(W//3+math.sin(i/10.0)*128), int(H//2-32+math.cos(i/10.0)*64), 32, 32, 0xA0008000+i*5)
        glib.timeout_add(1000+i*20, window.paint_and_vscroll,   -1)
        glib.timeout_add(2000+i*20, window.paint_crect,         int(W//3*2-math.sin(i/10.0)*128), int(H//2-16-math.cos(i/10.0)*64), 32, 32, 0x00F020FF-i*5)
        glib.timeout_add(2000+i*20, window.paint_and_vscroll,   +1)
    for i in range(200):
        glib.timeout_add(4000+i*20, window.split_vscroll,       max(1, i//50))
        glib.timeout_add(4000+i*20, window.paint_crect,         0, H//2-1, W, 2)

    try:
        gtk_main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
