#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""The tk client windows: focus and pointer buttons."""

import unittest
from types import SimpleNamespace

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
        for button in (1, 2, 3):
            event = SimpleNamespace(num=button, x=5, y=6)
            self.window.on_mouse_button_press(event)
            self.window.on_mouse_button_release(event)
        self.assertEqual(self.client.buttons(), [(b, pressed) for b in (1, 2, 3) for pressed in (True, False)])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
