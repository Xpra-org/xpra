#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The backing of a gtk3 OpenGL window is a texture, which cannot be larger than the maximum texture size,
whatever size the server asks for.
The usual limit of 16384 pixels does not fit on screen, so these tests lower it to 1024.
"""

import os
import unittest
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch

from xpra.os_util import gi_import, WIN32, OSX
from xpra.net.packet_type import WINDOW_CONFIGURE, WINDOW_MAP
from xpra.util.objects import typedict
from unit.process_test_util import DisplayContext

Gtk = gi_import("Gtk")

LIMIT = 1024


# (not imported from `window_server_size_test`, which uses fake backings)
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


class OpenGLWindowSizeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(DisplayContext())
        if os.name == "posix":
            # restored by the `DisplayContext`:
            os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
        try:
            from xpra.opengl import backing
            from xpra.client.gtk3.opengl.native_window import GLClientWindow
            # the drawing area needs the native handle of its window, see `GLDrawingArea.get_backing_handle`:
            # (ie: on MS Windows, this fails when the GTK libraries are not on the `PATH`)
            if WIN32:
                import xpra.platform.win32.gtk  # noqa: F401
            elif OSX:
                import xpra.platform.darwin.gdk3_bindings  # noqa: F401
        except ImportError as e:
            raise unittest.SkipTest(f"OpenGL is not available: {e}") from None
        cls.GLClientWindow = GLClientWindow
        cls.enterClassContext(patch.object(backing, "get_max_texture_size", lambda: LIMIT))
        cls.enterClassContext(patch.object(GLClientWindow, "MAX_BACKING_DIMS", (LIMIT, LIMIT)))
        # record the backing sizes that OpenGL rejects:
        cls.gl_errors = []
        gl_init = backing.GLWindowBackingBase.gl_init

        def checked_gl_init(self, *args, **kwargs):
            try:
                gl_init(self, *args, **kwargs)
            except ValueError:
                cls.gl_errors.append(self.size)
                raise

        cls.enterClassContext(patch.object(backing.GLWindowBackingBase, "gl_init", checked_gl_init))

    def setUp(self) -> None:
        from xpra.client.gui.fake_client import FakeWindowHost
        self.host = FakeWindowHost()
        self.host.subsystems["pointer"].send_mouse_position = lambda *_args: None
        self.sent = []
        self.host.subsystems["window"].send = lambda *packet: self.sent.append(packet)
        self.windows = []
        self.gl_errors.clear()

    def tearDown(self) -> None:
        for window in self.windows:
            window.destroy()
        process_events(timeout=0.1)
        self.windows.clear()
        self.host = None

    def make_window(self, scale: float, server_size: tuple[int, int]):
        from xpra.client.gui.window_border import WindowBorder
        display = scaled_display(scale)
        self.host.subsystems["display"] = display
        geometry = (100, 100, display.sx(server_size[0]), display.sy(server_size[1]))
        wid = len(self.windows) + 1
        window = self.GLClientWindow(self.host.get_subsystem, self.host.is_readonly, None, wid,
                                     geometry, server_size, typedict({"title": "opengl size test"}), False, typedict(),
                                     WindowBorder(False), (0, 0), 0, "no", None)
        self.host.subsystems["window"]._id_to_window[wid] = window
        self.windows.append(window)
        # the backing is created with the window, before the first configure event:
        backing_size = window._backing.size
        window.show_all()
        self.assertTrue(process_events(lambda: self.packets(WINDOW_MAP)), "the window was not mapped")
        try:
            context = window._backing.gl_context()
        except Exception as e:
            self.skipTest(f"no OpenGL context: {e}")
        if not context:
            self.skipTest("no OpenGL context")
        return window, display, backing_size

    def packets(self, packet_type: str) -> list:
        return [packet for packet in self.sent if packet[0] == packet_type]

    def configure_sizes(self) -> list[tuple[int, int]]:
        return [tuple(packet[2]["geometry"][2:]) for packet in self.packets(WINDOW_CONFIGURE)
                if "geometry" in packet[2]]

    def test_create(self) -> None:
        # at 0.5, 1025 server pixels are shown as 512 window pixels, which is within the window size limit:
        window, _, backing_size = self.make_window(0.5, (LIMIT + 1, 300))
        self.assertEqual(window.max_window_size, (512, 512))
        self.assertEqual(backing_size, (LIMIT, 300))
        # the server is told that it cannot have the size it asked for:
        self.assertEqual(tuple(self.packets(WINDOW_MAP)[0][4:6]), (LIMIT, 300))
        window.queue_draw()
        process_events(timeout=0.3)
        self.assertEqual(self.gl_errors, [])

    def test_server_resize(self) -> None:
        for scale in (1, 0.5):
            for move in (False, True):
                with self.subTest(scale=scale, move=move):
                    window, display, _ = self.make_window(scale, (LIMIT, 300))
                    self.sent.clear()
                    size = display.sx(3000), display.sy(300)
                    if move:
                        x, y = window.get_drawing_area_geometry()[:2]
                        window.move_resize(x + 10, y + 10, *size, 1, server_size=(3000, 300))
                    else:
                        window.resize(*size, 1, server_size=(3000, 300))
                    self.assertEqual(window._backing.size, (LIMIT, 300))
                    window.queue_draw()
                    process_events(timeout=0.5)
                    self.assertEqual(tuple(window.get_drawing_area_geometry()[2:]), (display.sx(LIMIT), size[1]))
                    self.assertEqual(window._backing.size, (LIMIT, 300))
                    # the window is already at the limit, but the server must still be told:
                    self.assertEqual(self.configure_sizes(), [(LIMIT, 300)])
                    self.assertEqual(self.gl_errors, [])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
