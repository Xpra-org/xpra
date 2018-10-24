#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import struct
from xpra.log import Logger
log = Logger()

import glib

from xpra.util import typedict
from tests.xpra.clients.fake_gtk_client import FakeGTKClient, gtk_main
from xpra.codecs.loader import load_codecs

load_codecs(encoders=False, decoders=True, csc=False)


class WindowAnim(object):

    def __init__(self, window_class, client, wid, W=630, H=480, animate=True):
        self.wid = wid
        self.window = window_class(client, None, wid, 10, 10, W, H, W, H, typedict({}), False, typedict({}), 0, None)
        self.window.show()
        self.paint_rect(0, 0, W, H, chr(255)*4*W*H)
        self.paint_rect(W//2-16, H//2-16, 32, 32, chr(0)*4*32*32)
        self.animate = animate
        self.damage = False
        client.handle_key_action = self.handle_key_action

    def handle_key_action(self, window, event):
        log.warn("handle_key_action(%s, %s)", window, event)
        if not event.pressed:
            self.animate = not self.animate
            if event.keyname in ("d", "D"):
                self.damage = not self.damage

    def scrollup(self, ydelta=1):
        if not self.animate:
            return True
        print("scrollup(%s) damage=%s" % (ydelta, self.damage))
        W, H = self.window.get_size()
        scrolls = (0, ydelta, W, H-ydelta, 0, -ydelta),
        self.window.draw_region(0, 0, W, H, "scroll", scrolls, W*4, 0, typedict({"flush" : 0}), [])
        dots = []
        v = int(time.time()*10000)
        for _ in range(W*ydelta):
            CB = 0xFF << ((self.wid % 4) * 8)
            c = struct.pack(b"@I", v & 0xFFFFFFFF & ~CB)
            dots.append(c)
        img_data = b"".join(dots)
        self.paint_rect(0, H-ydelta, W, ydelta, img_data)
        if self.damage:
            c = struct.pack(b"@I", 0xFFFFFFFF)
            img_data = c*10*16
            self.paint_rect(W-10, H//2-8-16, 10, 16, img_data)
            c = struct.pack(b"@I", 0x000000FF)
            img_data = c*10*16
            self.paint_rect(W-10, H//2-8, 10, 16, img_data)
        return True

    def scrolluponce(self, ydelta):
        self.scrollup(ydelta)
        return False

    def paint_rect(self, x=200, y=200, w=32, h=32, img_data="", options={}):
        self.window.draw_region(x, y, w, h, "rgb32", img_data, w*4, 0, typedict(options), [])


def main():
    import sys
    def argint(n, d):
        try:
            return int(sys.argv[n])
        except:
            return d
    N = argint(1, 1)        #number of windows
    delay = argint(2, 20)
    ydelta = argint(3, 1)
    animate = argint(4, 1)
    client = FakeGTKClient()
    print("%i windows, delay=%ims, ydelta=%i" % (N, delay, ydelta))
    window_classes = []
    try:
        from xpra.client.gtk2.client_window import ClientWindow
        window_classes.append(ClientWindow)
    except:
        pass
    try:
        from xpra.client.gl.gtk2.gtkgl_client_window import GLClientWindow
        window_classes.append(GLClientWindow)
    except:
        pass
    try:
        from xpra.client.gl.gtk2.nativegl_client_window import GLClientWindow   #@Reimport
        window_classes.append(GLClientWindow)
    except:
        pass
    for wid in range(N):
        window_class = window_classes[wid % len(window_classes)]
        anim = WindowAnim(window_class, client, wid, animate=animate)
        glib.idle_add(anim.scrolluponce, ydelta)
        glib.timeout_add(delay, anim.scrollup, ydelta)
    try:
        gtk_main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
