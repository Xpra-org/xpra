#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""The pyglet client windows: focus and pointer buttons."""

import unittest

from xpra.net.packet_type import POINTER_BUTTON, POINTER_MOTION
from xpra.client.gui.simple_pointer import SimplePointer
from unit.process_test_util import DisplayContext


class FakeClient:
    """ the minimal clients have no subsystems """

    def __init__(self):
        self.sent = []
        self.focus = []
        self.timers = []
        self.pointer = SimplePointer(self.send, self.timeout_add)

    def send(self, *packet):
        self.sent.append(packet)

    def timeout_add(self, _delay: int, fn) -> None:
        self.timers.append(fn)

    def run_timers(self) -> None:
        timers, self.timers = self.timers, []
        for fn in timers:
            fn()

    def update_focus(self, wid=0) -> None:
        self.focus.append(wid)

    def buttons(self) -> list[tuple[int, bool]]:
        return [(packet[4], packet[5]) for packet in self.sent if packet[0] == POINTER_BUTTON]

    def positions(self) -> list[tuple[int, int, int, int]]:
        """ the positions on the screen and relative to the window, of the pointer packets sent """
        positions = []
        for packet in self.sent:
            if packet[0] in (POINTER_MOTION, POINTER_BUTTON):
                pos, props = (packet[4], packet[5]) if packet[0] == POINTER_MOTION else (packet[6], packet[7])
                positions.append(tuple(pos) + tuple(props["window-position"]))
        return positions


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

    def test_position(self) -> None:
        # the position on the screen, and relative to the window, top-down:
        from pyglet.window import mouse
        from xpra.client.pyglet.window import MOTION_Y_OFFSET
        wx, wy = self.window.get_location()
        h = self.window.height
        expected = (wx + 30, wy + 40, 30, 40)
        self.window.on_mouse_press(30, h - 40, mouse.LEFT, 0)
        # pyglet's motion events are one pixel lower on X11:
        y = h - 40 - MOTION_Y_OFFSET
        self.window.on_mouse_motion(30, y, 0, 0)
        self.window.on_mouse_drag(30, y, 0, 0, mouse.LEFT, 0)
        # (the motion packets are sent at most every few milliseconds)
        self.client.run_timers()
        positions = self.client.positions()
        self.assertEqual(positions, [expected] * 3)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
