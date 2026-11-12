#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.common import Packet


class TestWindowIconValidation(unittest.TestCase):

    def make_handler(self):
        from xpra.client.subsystem.window.window_icon import WindowIcon

        class Handler(WindowIcon):
            __slots__ = ("overlay_image", "queued")

            def add_decode_work(self, *args) -> None:
                self.queued = args

        return Handler()

    def test_raw_icon_validation(self):
        handler = self.make_handler()
        handler._process_icon(Packet("window-icon", 1, 2, 2, "RGBA", b"\0" * 16))
        self.assertEqual(handler.queued[1:5], (1, 2, 2, "RGBA"))
        with self.assertRaises(ValueError):
            handler._process_icon(Packet("window-icon", 1, 2, 2, "RGBA", b"short"))
        with self.assertRaises(ValueError):
            handler._process_icon(Packet("window-icon", 1, 1025, 1, "RGBA", b""))

    def test_default_icon_cannot_carry_peer_data(self):
        handler = self.make_handler()
        with self.assertRaises(ValueError):
            handler._process_icon(Packet("window-icon", 1, 0, 0, "default", b"data"))


if __name__ == "__main__":
    unittest.main()
