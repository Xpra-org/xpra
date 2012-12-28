#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pygtk
pygtk.require('2.0')
import gtk
import gobject

from wimpiggy.log import Logger
log = Logger()

from xpra.gl.gl_client_window import GLClientWindow

class FakeClient(object):
    def __init__(self):
        self.supports_mmap = False
        self.mmap = None
        self.window_configure = True
        self._focused = None
        self.readonly = False
        self.title = "test"
        self._id_to_window = {}
        self._window_to_id = {}

    def send_refresh(self, *args):
        log.info("send_refresh(%s)", args)

    def send_refresh_all(self, *args):
        log.info("send_refresh_all(%s)", args)

    def send(self, *args):
        log.info("send(%s)", args)

    def send_positional(self, *args):
        log.info("send_positional(%s)", args)

    def update_focus(self, *args):
        log.info("update_focus(%s)", args)

    def quit(self, *args):
        log.info("quit(%s)", args)

    def handle_key_action(self, *args):
        log.info("handle_key_action(%s)", args)

    def send_mouse_position(self, *args):
        log.info("send_mouse_position(%s)", args)

    def mask_to_names(self, *args):
        return []


def main():
    import logging
    logging.basicConfig(format="%(asctime)s %(message)s")
    logging.root.setLevel(logging.DEBUG)
    
    w = 200
    h = 100

    window = GLClientWindow(FakeClient(), None, 1, 0, 0, w, h, {}, False, {}, 0)
    window.show()
    def update_backing(*args):
        log.info("update_backing(%s)", args)
        from xpra.codec_constants import YUV444P
        import random
        y = chr(int(random.random()*256.0))
        u = chr(int(random.random()*256.0))
        v = chr(int(random.random()*256.0))
        img_data = [y*w*h*2, u*w*h*2, v*w*h*2]
        rowstrides = [w, w, w]
        pixel_format = YUV444P
        def update_done(*args):
            log.info("update_done(%s)", args)
        window._backing.do_gl_paint(0, 0, w, h, img_data, rowstrides, pixel_format, [update_done])
        return True
    def initial_update(*args):
        update_backing()
        return False
    #gobject.idle_add(initial_update)
    gobject.timeout_add(10, initial_update)
    gobject.timeout_add(1000*5, update_backing)
    gtk.main()


if __name__ == '__main__':
    main()
