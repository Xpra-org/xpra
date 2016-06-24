#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
from xpra.log import Logger
log = Logger()

import glib

from xpra.util import typedict
from tests.xpra.clients.fake_gtk_client import FakeGTKClient, gtk_main
from xpra.codecs.loader import load_codecs

load_codecs(encoders=False, decoders=True, csc=False)


class WindowAnim(object):

    def __init__(self, window_class, client, wid=1, W=630, H=480):
        self.wid = wid
        self.window = window_class(client, None, wid, 10, 10, W, H, W, H, typedict({}), False, typedict({}), 0, None)
        self.window.show()
        self.paint_rect(0, 0, W, H, chr(255)*4*W*H)
        self.paint_rect(W//2-16, H//2-16, 64, 64, chr(0)*4*64*64)
        self.counter = 0
        self.delta_x = 0
        self.delta_y = 0

    def paint_rect(self, x=200, y=200, w=32, h=32, img_data=None, options={}):
        assert img_data
        self.window.draw_region(x, y, w, h, "rgb32", img_data, w*4, 0, typedict(options), [])

    def movearound(self, ydelta=1):
        self.counter += 1
        RADIUS = 128
        target_x = int(math.sin(self.counter/10.0) * RADIUS)
        target_y = int(math.cos(self.counter/10.0) * RADIUS)
        dx = target_x - self.delta_x
        dy = target_y - self.delta_y
        W, H = self.window.get_size()
        scrolls = (RADIUS, RADIUS, W-RADIUS*2, H-RADIUS*2, dx, dy),
        self.window.draw_region(0, 0, W, H, "scroll", scrolls, W*4, 0, typedict({"flush" : 0}), [])
        self.delta_x = target_x
        self.delta_y = target_y
        return True


def main():
    client = FakeGTKClient()
    try:
        from xpra.client.gl.gtk2.gl_client_window import GLClientWindow
        window_class = GLClientWindow
    except:
        from xpra.client.gtk2.border_client_window import BorderClientWindow
        window_class = BorderClientWindow
    anim = WindowAnim(window_class, client)
    glib.timeout_add(100, anim.movearound)
    try:
        gtk_main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
