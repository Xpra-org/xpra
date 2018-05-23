#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pygtk
pygtk.require('2.0')
import gtk
import gobject

from xpra.log import Logger
log = Logger()
log.enable_debug()

from tests.xpra.clients.fake_client import FakeClient


def gl_backing_test(gl_client_window_class=None, w=200, h=100):
    window = gl_client_window_class(FakeClient(), None, 1, 0, 0, w, h, {}, False, {}, 0)
    window.show()
    def update_backing(*args):
        log("update_backing(%s)", args)
        import random
        y = chr(int(random.random()*256.0))
        u = chr(int(random.random()*256.0))
        v = chr(int(random.random()*256.0))
        img_data = [y*w*h*2, u*w*h*2, v*w*h*2]
        rowstrides = [w, w, w]
        pixel_format = "YUV444P"
        def update_done(*args):
            log("update_done(%s)", args)
        window._backing.do_gl_paint(0, 0, w, h, img_data, rowstrides, pixel_format, [update_done])
        return True
    def initial_update(*args):
        update_backing()
        return False
    gobject.timeout_add(10, initial_update)
    gobject.timeout_add(1000*5, update_backing)


def main():
    from xpra.client.gl.gtk2.nativegl_client_window import GLClientWindow
    gl_backing_test(gl_client_window_class=GLClientWindow)
    gtk.main()


if __name__ == '__main__':
    main()
