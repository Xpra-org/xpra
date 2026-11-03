#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""The pyglet client windows: focus and pointer buttons."""

import unittest

from xpra.net.packet_type import POINTER_BUTTON
from unit.process_test_util import DisplayContext


class FakeClient:
    """ the minimal clients have no subsystems """

    def __init__(self):
        self.sent = []
        self.focus = []

    def send(self, *packet):
        self.sent.append(packet)

    def update_focus(self, wid=0) -> None:
        self.focus.append(wid)

    def buttons(self) -> list[tuple[int, bool]]:
        return [(packet[4], packet[5]) for packet in self.sent if packet[0] == POINTER_BUTTON]


class PygletWindowTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import pyglet
            assert pyglet
        except ImportError:
            raise unittest.SkipTest("pyglet is not installed")
        cls.enterClassContext(DisplayContext())

    def setUp(self) -> None:
        from xpra.client.pyglet.window import ClientWindow
        self.client = FakeClient()
        self.window = ClientWindow(self.client, 5, 10, 20, 200, 100, {"title": "test"})
        # we don't need the event logger:
        self.window.remove_handlers()

    def tearDown(self) -> None:
        self.window.close()

    def test_focus(self) -> None:
        self.window.on_activate()
        self.assertEqual(self.client.focus, [5])

    def test_buttons(self) -> None:
        # pyglet's buttons are bit flags:
        from pyglet.window import mouse
        for button in (mouse.LEFT, mouse.MIDDLE, mouse.RIGHT, mouse.MOUSE4, mouse.MOUSE5):
            self.window.on_mouse_press(5, 6, button, 0)
            self.window.on_mouse_release(5, 6, button, 0)
        self.assertEqual(self.client.buttons(), [(b, pressed) for b in (1, 2, 3, 8, 9) for pressed in (True, False)])

    def test_wheel(self) -> None:
        from pyglet.window import mouse
        for scroll_x, scroll_y in ((0, 1), (0, -1), (-1, 0), (1, 0)):
            self.window.on_mouse_scroll(5, 6, scroll_x, scroll_y)
        self.assertEqual(self.client.buttons(), [(b, pressed) for b in (4, 5, 6, 7) for pressed in (True, False)])
        # pyglet also reports the release of the wheel buttons 4 and 5, as `MOUSE4` and `MOUSE5`:
        self.client.sent.clear()
        self.window.on_mouse_release(5, 6, mouse.MOUSE4, 0)
        self.window.on_mouse_release(5, 6, mouse.MOUSE5, 0)
        self.assertEqual(self.client.buttons(), [])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
