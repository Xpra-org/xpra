#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.net.common import BACKWARDS_COMPATIBLE, Packet
from xpra.util.objects import AdHocStruct


class CursorClientTest(unittest.TestCase):

    @staticmethod
    def make_cursor():
        from xpra.client.subsystem.cursor import CursorClient

        class Handler(CursorClient):
            __slots__ = ("queued", )

            def add_decode_work(self, *args) -> None:
                self.queued = args

        cursor = Handler()
        cursor.enabled = True
        return cursor

    def test_default_size_is_in_server_logical_pixels(self):
        from xpra.client.subsystem.cursor import CursorClient

        display = AdHocStruct()
        display.xscale = display.yscale = 2
        client = AdHocStruct()
        client.subsystems = {"display": display}
        with patch("xpra.platform.gui.get_default_cursor_size",
                   return_value=(24, 24)), \
             patch("xpra.platform.gui.get_max_cursor_size",
                   return_value=(64, 64)):
            cursor = CursorClient()
            cursor.client = client
            caps = cursor.get_caps()["cursor"]

        self.assertEqual(caps["default"], (12, 12))
        self.assertEqual(caps["max"], (64, 64))
        if BACKWARDS_COMPATIBLE:
            self.assertEqual(caps["size"], 12)

    def test_cursor_hotspot_is_clamped(self):
        cursor = self.make_cursor()
        pixels = b"\0" * 8
        cursor._process_data(Packet("cursor-data", "raw", 1, 2, 0, 2, 9, pixels, ""))
        self.assertEqual(cursor.queued[1:], ("raw", 1, 2, 0, 1, 9, pixels, ""))
        cursor._process_data(Packet("cursor-data", "raw", 2, 1, 2, 0, 1, pixels, ""))
        self.assertEqual(cursor.queued[1:6], ("raw", 2, 1, 1, 0))


if __name__ == '__main__':
    unittest.main()
