#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from collections import deque
from unittest.mock import Mock, patch

from xpra.net.common import Packet
from xpra.client.subsystem.window import draw
from xpra.client.subsystem.window.draw import WindowDraw


class Draw(WindowDraw):
    """ just enough of a client to call `_do_draw` directly """

    def __init__(self, window):  # pylint: disable=super-init-not-called
        self.window = window
        self._draw_counter = 0
        self.pixel_counter = deque(maxlen=100)
        self.acks = []

    def get_window(self, _wid):
        return self.window

    def get_subsystem(self, _name):
        return None

    @staticmethod
    def idle_add(fn, *args):
        fn(*args)

    def send_now(self, *args):
        self.acks.append(args)


def mmap_packet(img_data) -> Packet:
    chunks = ((8, 400), )
    return Packet("window-draw", 1, 0, 0, 10, 10, "mmap", img_data, 1, 40, {"chunks": chunks})


class WindowDrawTest(unittest.TestCase):

    def test_overloaded_pixel_data(self):
        # v7 servers running in backwards compatible mode duplicate the mmap `chunks` in the pixel data:
        window = Mock()
        with patch.object(draw, "BACKWARDS_COMPATIBLE", True):
            Draw(window)._do_draw(mmap_packet(((8, 400), )))
        window.draw_region.assert_called_once()
        args = window.draw_region.call_args.args
        self.assertEqual(args[4], "mmap")
        self.assertEqual(args[5], b"")
        self.assertEqual(args[7]["chunks"], ((8, 400), ))

    def test_overloaded_pixel_data_rejected(self):
        window = Mock()
        with patch.object(draw, "BACKWARDS_COMPATIBLE", False):
            with self.assertRaises((TypeError, ValueError)):
                Draw(window)._do_draw(mmap_packet(((8, 400), )))
        window.draw_region.assert_not_called()

    def test_buffer_pixel_data(self):
        for backwards_compatible in (False, True):
            window = Mock()
            with patch.object(draw, "BACKWARDS_COMPATIBLE", backwards_compatible):
                Draw(window)._do_draw(mmap_packet(b""))
            window.draw_region.assert_called_once()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
