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
from unittest.mock import Mock, patch

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

    def make_window(self, subsystems, readonly=False):
        from xpra.client.win32.window import ClientWindow
        sent = []
        subsystems.setdefault("window", SimpleNamespace(send=lambda *packet: sent.append(packet)))
        window = SimpleNamespace(get_subsystem=subsystems.get, is_readonly=lambda: readonly,
                                 wid=7, x=20, y=40, width=200, height=100,
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

    def test_system_geometry_large_coordinates(self) -> None:
        import win32con
        from xpra.client.win32.window import system_geometry
        # beyond the 16-bit range: the frame must still surround the client area
        for x, y in ((40000, 50000), (-40000, -50000), (100, 100)):
            with self.subTest(x=x, y=y):
                wx, wy, ww, wh = system_geometry(x, y, 640, 480, win32con.WS_OVERLAPPEDWINDOW, 0)
                self.assertTrue(x - 64 < wx <= x and y - 128 < wy <= y, (wx, wy))
                self.assertTrue(wx + ww >= x + 640 and wy + wh >= y + 480, (ww, wh))

    def test_map_drawable_geometry(self) -> None:
        from xpra.client.win32 import window as native

        # At 2x, widths 200 and 201 both round to 100 server pixels.
        # At 0.5x, height 50 could have come from 99 or 100 server pixels.
        display = SimpleNamespace(cx=lambda w: round(w / 2), cy=lambda h: round(h * 2))
        for origin_ok, rect_ok, size, expected in (
            (True, True, (201, 50), (201, 50, 100, 99)),
            (False, True, (210, 60), (210, 60, 105, 120)),
            (True, False, (210, 60), (200, 50, 100, 99)),
            (None, True, (210, 60), (210, 60, 105, 120)),
            (True, None, (210, 60), (200, 50, 100, 99)),
            (True, True, (210, 0), (200, 50, 100, 99)),
        ):
            with self.subTest(origin_ok=origin_ok, rect_ok=rect_ok, size=size):
                window = Mock(hwnd=1, x=20, y=30, width=200, height=50, _backing_size=(100, 99))
                window.get_subsystem.return_value = display
                window.is_OR.return_value = True

                def origin(hwnd, point):
                    if origin_ok is None:
                        raise OSError()
                    point._obj.x, point._obj.y = -40, 70
                    return origin_ok

                def client_rect(hwnd, rect):
                    if rect_ok is None:
                        raise OSError()
                    rect._obj.right, rect._obj.bottom = size
                    return rect_ok

                with patch.object(native, "ClientToScreen", origin), patch.object(native, "GetClientRect", client_rect):
                    native.ClientWindow.window_created(window)
                window.backing.init.assert_called_once_with(*expected)
                self.assertEqual((window.width, window.height), expected[:2])
                self.assertEqual((window.x, window.y), (-40, 70) if origin_ok else (20, 30))
                window.emit.assert_called_once_with("mapped")

    def test_no_display_scaling(self) -> None:
        window, sent = self.make_window({})
        window.send_configure()
        self.assertEqual(sent[0][2]["geometry"], (20, 40, 200, 100))
        self.assertEqual(sent[0][2]["monitor"], {"index": 1, "position": (10, 20)})

    def test_readonly(self) -> None:
        # the server would ignore it:
        window, sent = self.make_window({"display": Display()}, readonly=True)
        window.send_configure()
        self.assertEqual(sent, [])
        self.assertEqual(window.state_updates, {})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
