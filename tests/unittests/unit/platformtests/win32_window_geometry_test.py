#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Verify the native window frame geometry."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.os_util import WIN32


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class Win32WindowGeometryTest(unittest.TestCase):

    def test_system_geometry_large_coordinates(self) -> None:
        import win32con
        from xpra.client.win32.window import system_geometry
        # beyond the 16-bit range: the frame must still surround the client area
        for x, y in ((40000, 50000), (-40000, -50000), (100, 100)):
            with self.subTest(x=x, y=y):
                wx, wy, ww, wh = system_geometry(x, y, 640, 480, win32con.WS_OVERLAPPEDWINDOW, 0)
                self.assertTrue(x - 64 < wx <= x and y - 128 < wy <= y, (wx, wy))
                self.assertTrue(wx + ww >= x + 640 and wy + wh >= y + 480, (ww, wh))

    def test_system_geometry_dpi(self) -> None:
        import win32con
        from xpra.client.win32.window import system_geometry
        from xpra.platform.win32.dpi import adjust_window_rect_for_dpi
        from xpra.platform.win32.common import RECT
        if not adjust_window_rect_for_dpi(RECT(), win32con.WS_OVERLAPPEDWINDOW, False, 0, 96):
            self.skipTest("AdjustWindowRectExForDpi is not available")
        style = win32con.WS_OVERLAPPEDWINDOW
        w96, h96 = system_geometry(0, 0, 640, 480, style, 0, dpi=96)[2:]
        w192, h192 = system_geometry(0, 0, 640, 480, style, 0, dpi=192)[2:]
        # the frame is thicker at a higher DPI, the client area is the same:
        self.assertGreater(w192, w96)
        self.assertGreater(h192, h96)
        # popups have no frame at any DPI:
        self.assertEqual(system_geometry(10, 20, 640, 480, win32con.WS_POPUP, 0, dpi=192), (10, 20, 640, 480))

    def test_fit_frame_to_dpi(self) -> None:
        import win32con
        from xpra.client.win32 import window as native

        def frame(x, y, w, h, style, exstyle, has_menu=False, dpi=0):
            # without a DPI, the system DPI is used: 96
            border = (dpi or 96) // 12
            return x - border, y - border * 3, w + border * 2, h + border * 4

        for dpi, current, default_position, expected in (
            # created at 96 DPI and landed on a 96 DPI monitor: nothing to do
            (96, (92, 4, 656, 512), False, None),
            # same DPI, but clamped by the size constraints (ie: OpenGL texture size limit): leave it
            (96, (92, 4, 500, 512), False, None),
            # landed on a 192 DPI monitor: the frame is too thin
            (192, (92, 4, 656, 512), False, (84, -20, 672, 544)),
            # the OS chose the position: keep it
            (192, (300, 200, 656, 512), True, (300, 200, 672, 544)),
            # `GetDpiForWindow` is not available
            (0, (92, 4, 656, 512), False, None),
        ):
            with self.subTest(dpi=dpi, default_position=default_position):
                window = SimpleNamespace(style=win32con.WS_OVERLAPPEDWINDOW, x=-1, y=-1, width=1, height=1)
                calls = []

                def get_window_rect(hwnd, rect):
                    r = rect._obj
                    r.left, r.top = current[:2]
                    r.right, r.bottom = current[0] + current[2], current[1] + current[3]
                    return True

                with (patch.object(native, "get_window_dpi", lambda hwnd: dpi),
                      patch.object(native, "system_geometry", frame),
                      patch.object(native, "GetWindowRect", get_window_rect),
                      patch.object(native, "SetWindowPos", lambda hwnd, after, *geom: calls.append(geom[:4]))):
                    native.ClientWindow.fit_frame_to_dpi(window, 1, 0, (100, 28, 640, 480), default_position)
                self.assertEqual(calls, [expected] if expected else [])

    def test_measure_created_window(self) -> None:
        from xpra.client.win32 import window as native

        def client_to_screen(hwnd, point):
            point._obj.x, point._obj.y = 40000, -50000
            return True

        def get_client_rect(hwnd, rect):
            rect._obj.right, rect._obj.bottom = 200, 160
            return True

        display = SimpleNamespace(cx=lambda w: w // 2, cy=lambda h: h // 2)
        client = SimpleNamespace(get_subsystem=lambda name: display)
        window = SimpleNamespace(client=client, _backing_size=(101, 99))
        with (patch.object(native, "ClientToScreen", client_to_screen),
              patch.object(native, "GetClientRect", get_client_rect)):
            native.ClientWindow.measure_created_window(window, 1, (200, 198))
        self.assertEqual((window.x, window.y, window.width, window.height), (40000, -50000, 200, 160))
        self.assertEqual(window._backing_size, (101, 80))


if __name__ == "__main__":
    unittest.main()
