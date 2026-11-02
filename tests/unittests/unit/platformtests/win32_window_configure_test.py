#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The win32 windows send their own `window-configure` packets.
These tests are skipped on non-Windows platforms.
"""

import unittest
from types import SimpleNamespace, MethodType

from xpra.os_util import WIN32


class Display:
    @staticmethod
    def crect(x, y, w, h):
        return x // 2, y // 2, w // 2, h // 2

    @staticmethod
    def get_server_position(pos):
        return pos[0] + 100, pos[1]

    @staticmethod
    def cp(x, y):
        return x // 2, y // 2


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class Win32ConfigureTest(unittest.TestCase):

    def make_window(self, subsystems):
        from xpra.client.win32.window import ClientWindow
        sent = []
        subsystems.setdefault("window", SimpleNamespace(send=lambda *packet: sent.append(packet)))
        client = SimpleNamespace(get_subsystem=subsystems.get)
        window = SimpleNamespace(client=client, wid=7, x=20, y=40, width=200, height=100,
                                 state_updates={"fullscreen": True}, resize_counter=3,
                                 pop_client_properties=lambda: {},
                                 get_monitor_position=lambda: {"index": 1, "position": (10, 20)})
        for name in ("get_server_geometry", "get_server_monitor_position", "send_configure"):
            setattr(window, name, MethodType(getattr(ClientWindow, name), window))
        return window, sent

    def test_send_configure(self) -> None:
        window, sent = self.make_window({"display": Display()})
        window.send_configure()
        self.assertEqual(sent, [("window-configure", 7, {
            "state": {"fullscreen": True},
            "geometry": (110, 20, 100, 50),
            "resize-counter": 3,
            "raw-position": (10, 20),
            "monitor": {"index": 1, "position": (5, 10)},
        })])
        self.assertEqual(window.state_updates, {})

    def test_no_display_scaling(self) -> None:
        window, sent = self.make_window({})
        window.send_configure()
        self.assertEqual(sent[0][2]["geometry"], (20, 40, 200, 100))
        self.assertEqual(sent[0][2]["monitor"], {"index": 1, "position": (10, 20)})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
