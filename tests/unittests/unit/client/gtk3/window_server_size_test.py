#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Real gtk3 client windows, resized by the server.
With fractional scaling, several server sizes map to the same window size:
at 0.8, 1193 and 1192 are both shown as 954 window pixels,
and 954 window pixels convert back to 1192.
The window must keep the size the server asked for, and report that size back to it.
"""

import os
import unittest
from time import monotonic, sleep
from types import SimpleNamespace

# no OpenGL or real backing needed:
os.environ["XPRA_USE_FAKE_BACKING"] = "1"

from xpra.os_util import gi_import  # noqa: E402
from xpra.net.packet_type import WINDOW_CONFIGURE, WINDOW_MAP  # noqa: E402
from xpra.util.objects import typedict  # noqa: E402
from unit.process_test_util import DisplayContext  # noqa: E402

Gtk = gi_import("Gtk")


def scaled_display(scale: float):
    return SimpleNamespace(
        xscale=scale, yscale=scale,
        sx=lambda v: round(v * scale), sy=lambda v: round(v * scale),
        cx=lambda v: round(v / scale), cy=lambda v: round(v / scale),
        get_root_size=lambda: (8192, 8192), screen_sizes=[],
    )


def process_events(condition=None, timeout: float = 5) -> bool:
    """ run the main loop until `condition` is true, or for `timeout` seconds if there is no condition """
    end = monotonic() + timeout
    while monotonic() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if condition and condition():
            return True
        sleep(0.01)
    return bool(condition and condition())


class MaxWindowSizeTest(unittest.TestCase):

    @staticmethod
    def max_window_size(scale: float, is_gl: bool, max_window_size=(0, 0)) -> tuple[int, int]:
        from xpra.client.gtk3.window.base import GTKClientWindowBase
        display = scaled_display(scale)
        window = SimpleNamespace(max_window_size=max_window_size, is_GL=lambda: is_gl,
                                 MAX_VIEWPORT_DIMS=(16384, 16384), MAX_BACKING_DIMS=(16384, 16384),
                                 sx=display.sx, sy=display.sy, cx=display.cx, cy=display.cy)
        GTKClientWindowBase.init_max_window_size(window)
        return window.max_window_size

    def test_max_window_size(self) -> None:
        for scale, is_gl, max_window_size, expected in (
            # the default limits of the other windows are not a size hint:
            (1, False, (0, 0), (0, 0)),
            (2, False, (0, 0), (0, 0)),
            (0.5, False, (0, 0), (8192, 8192)),
            # 16k is the maximum texture size of an OpenGL window:
            (1, True, (0, 0), (16384, 16384)),
            # 16384 server pixels are 3277 window pixels, which convert back to 16385:
            (0.2, True, (0, 0), (3276, 3276)),
            (1, True, (1000, 0), (1000, 16384)),
        ):
            with self.subTest(scale=scale, is_gl=is_gl, max_window_size=max_window_size):
                self.assertEqual(self.max_window_size(scale, is_gl, max_window_size), expected)


class ServerSizeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(DisplayContext())

    def setUp(self) -> None:
        from xpra.client.gui.fake_client import FakeWindowHost
        self.host = FakeWindowHost()
        self.host.subsystems["pointer"].send_mouse_position = lambda *_args: None
        self.sent = []
        self.host.subsystems["window"].send = lambda *packet: self.sent.append(packet)
        self.windows = []

    def tearDown(self) -> None:
        for window in self.windows:
            window.destroy()
        process_events(timeout=0.1)
        # drop our references, so they are freed before the display is closed:
        self.windows.clear()
        self.host = None

    def make_window(self, scale: float, server_size: tuple[int, int], max_window_size=(0, 0)):
        from xpra.client.gui.window_border import WindowBorder
        from xpra.client.gtk3.window.window import ClientWindow
        display = scaled_display(scale)
        self.host.subsystems["display"] = display
        geometry = (100, 100, display.sx(server_size[0]), display.sy(server_size[1]))
        wid = len(self.windows) + 1
        window = ClientWindow(self.host.get_subsystem, self.host.is_readonly, None, wid,
                              geometry, server_size, typedict({"title": "server size test"}), False, typedict(),
                              WindowBorder(False), max_window_size, 0, "no", None)
        self.host.subsystems["window"]._id_to_window[wid] = window
        self.windows.append(window)
        window.show_all()
        self.assertTrue(process_events(lambda: self.packets(WINDOW_MAP)), "the window was not mapped")
        return window, display

    def packets(self, packet_type: str) -> list:
        return [packet for packet in self.sent if packet[0] == packet_type]

    def configure_sizes(self) -> list[tuple[int, int]]:
        return [tuple(packet[2]["geometry"][2:]) for packet in self.packets(WINDOW_CONFIGURE)
                if "geometry" in packet[2]]

    @staticmethod
    def window_size(window) -> tuple[int, int]:
        return tuple(window.get_drawing_area_geometry()[2:])

    def server_resize(self, window, display, server_size: tuple[int, int], move=False) -> None:
        """ what the `window-resized` and `window-move-resize` packet handlers do """
        size = display.sx(server_size[0]), display.sy(server_size[1])
        if move:
            x, y = window.get_drawing_area_geometry()[:2]
            window.move_resize(x + 10, y + 10, *size, 1, server_size=server_size)
        else:
            window.resize(*size, 1, server_size=server_size)
        self.assertTrue(process_events(lambda: self.window_size(window) == size), "the window was not resized")
        # the configure events that follow a resize may report the previous size first:
        process_events(timeout=0.3)

    def assert_server_size(self, window, server_size: tuple[int, int]) -> None:
        self.assertEqual(window._backing.size, server_size)
        # the last `window-configure` packet sent has the size the server asked for:
        configure_sizes = self.configure_sizes()
        if configure_sizes:
            self.assertEqual(configure_sizes[-1], server_size)
        self.sent.clear()
        window.send_configure()
        self.assertEqual(self.configure_sizes(), [server_size])
        self.sent.clear()

    def test_map(self) -> None:
        # 1193x847 is shown as 954x678, which converts back to 1192x848:
        window = self.make_window(0.8, (1193, 847))[0]
        self.assertEqual(self.window_size(window), (954, 678))
        self.assertEqual(tuple(self.packets(WINDOW_MAP)[0][4:6]), (1193, 847))
        self.assert_server_size(window, (1193, 847))

    def test_server_resize(self) -> None:
        for move in (False, True):
            with self.subTest(move=move):
                window, display = self.make_window(0.8, (1193, 847))
                for server_size in (
                    (1192, 875),
                    # the window size does not change:
                    (1193, 875),
                    (1192, 875),
                    # 847 converts back to 848:
                    (1193, 847),
                    (1192, 900),
                    (1193, 847),
                ):
                    self.sent.clear()
                    self.server_resize(window, display, server_size, move)
                    self.assert_server_size(window, server_size)

    def test_user_resize(self) -> None:
        # a resize by the user keeps the server width where the window width does not change:
        window = self.make_window(0.8, (1193, 847))[0]
        x, y = window.get_drawing_area_geometry()[:2]
        self.sent.clear()
        window.update_configure_geometry("test", (x, y, 954, 720))
        self.assertEqual(window._backing.size, (1193, 900))
        self.assertEqual(self.configure_sizes(), [(1193, 900)])
        # and going back to the original size gives the server's size, not 1192x848:
        self.sent.clear()
        window.update_configure_geometry("test", (x, y, 954, 678))
        self.assertEqual(window._backing.size, (1193, 847))
        self.assertEqual(self.configure_sizes(), [(1193, 847)])

    def test_max_window_size(self) -> None:
        # the server asks for more than the maximum window size, which is in local pixels:
        window = self.make_window(1, (400, 300), max_window_size=(500, 400))[0]
        self.sent.clear()
        x, y = window.get_drawing_area_geometry()[:2]
        window.move_resize(x + 10, y + 10, 800, 300, 1, server_size=(800, 300))
        self.assertTrue(process_events(lambda: self.window_size(window) == (500, 300)), "the window was not resized")
        process_events(timeout=0.3)
        self.assertEqual(window._backing.size, (500, 300))
        self.assertEqual(self.configure_sizes()[-1], (500, 300))
        # the window is already at the limit, so its size does not change:
        # there is no configure event to tell the server that it cannot have the size it asked for
        self.sent.clear()
        window.resize(900, 300, 2, server_size=(900, 300))
        self.assertEqual(self.window_size(window), (500, 300))
        self.assertEqual(self.configure_sizes(), [(500, 300)])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
