#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import unittest

from xpra.util import AdHocStruct
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.server.rfb.rfb_source import RFBSource

def noop(*_args):
    pass


class TestRFB(unittest.TestCase):

    def test_rfb_source(self):
        #fake protocol:
        p = AdHocStruct()
        p.send = noop
        p.queue_size = lambda : 1
        #fake window:
        window = AdHocStruct()
        def get_image(x, y, w, h):
            stride = (w+8)*4
            pixels = b"0"*stride*h
            return ImageWrapper(x, y, w, h, pixels, "BGRX", 24, stride, 4)
        window.get_image = get_image
        window.acknowledge_changes = noop
        for protocol in (p, None):
            s = RFBSource(protocol, True)
            assert s.get_info()
            s.get_window_info(())
            s.ping()
            s.keys_changed()
            s.set_default_keymap()
            s.send_cursor()
            s.send_server_event()
            s.update_mouse()
            s.damage(1, window, 0, 0, 1024, 768, {"polling" : protocol is None})
            s.damage(1, window, 0, 0, 2, 2, {"polling" : protocol is None})
            s.send_clipboard("foo")
            s.bell()
            assert not s.is_closed()
            s.close()
            #noop:
            s.damage(1, window, 0, 0, 2, 2, {"polling" : protocol is None})
            assert s.is_closed()


def main():
    unittest.main()

if __name__ == '__main__':
    main()
