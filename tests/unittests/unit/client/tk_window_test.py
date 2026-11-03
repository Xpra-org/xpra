#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""The tk client windows: focus and pointer buttons."""

import unittest
from types import SimpleNamespace

from xpra.net.packet_type import POINTER_MOTION
from unit.process_test_util import DisplayContext
from unit.client.pyglet_window_test import FakeClient


class TkWindowTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import tkinter
            assert tkinter
        except ImportError:
            raise unittest.SkipTest("tkinter is not installed")
        cls.enterClassContext(DisplayContext())

    def setUp(self) -> None:
        # (importing the tk client opens the display)
        from xpra.client.tk.window import ClientWindow
        self.client = FakeClient()
        self.window = ClientWindow(self.client, 5, 10, 20, 200, 100, {"title": "test"})

    def tearDown(self) -> None:
        self.window.destroy()

    def test_focus(self) -> None:
        self.window.on_focus_in(SimpleNamespace())
        self.assertEqual(self.client.focus, [5])

    def test_buttons(self) -> None:
        # (Tk 8.6 on X11 also sends the wheel as buttons 4 to 7)
        buttons = (1, 2, 3, 4, 5, 6, 7, 8, 9)
        for button in buttons:
            event = SimpleNamespace(num=button, x_root=100, y_root=80)
            self.window.on_mouse_button_press(event)
            self.window.on_mouse_button_release(event)
        self.assertEqual(self.client.buttons(), [(b, pressed) for b in buttons for pressed in (True, False)])

    def test_wheel(self) -> None:
        # Tk 8.7 and later: the horizontal wheel has the shift modifier
        for delta, state in ((120, 0), (-240, 0), (120, 1), (-120, 1), (0, 0), (30, 0)):
            self.window.on_mouse_wheel(SimpleNamespace(delta=delta, state=state, x_root=100, y_root=80))
        clicks = (4, 5, 5, 6, 7, 4)
        self.assertEqual(self.client.buttons(), [(b, pressed) for b in clicks for pressed in (True, False)])

    def test_position(self) -> None:
        # the position on the screen, and relative to the window:
        # (`event.x` and `event.y` are relative to the widget under the pointer)
        self.window.update()
        wx, wy = self.window.winfo_rootx(), self.window.winfo_rooty()
        event = SimpleNamespace(num=1, x=0, y=0, x_root=wx + 30, y_root=wy + 40)
        self.window.on_mouse_motion(event)
        self.window.on_mouse_button_press(event)
        positions = [packet[4] if packet[0] == POINTER_MOTION else packet[6] for packet in self.client.sent]
        self.assertEqual(positions, [(wx + 30, wy + 40, 30, 40)] * 2)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
