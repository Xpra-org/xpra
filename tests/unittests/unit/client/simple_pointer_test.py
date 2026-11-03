#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""The pointer packets of the minimal clients (pyglet, qt6 and tk)."""

import unittest

from xpra.net.packet_type import POINTER_BUTTON, POINTER_MOTION
from xpra.client.gui.simple_pointer import SimplePointer, split_position

POS = (100, 80, 10, 20)


class SimplePointerTest(unittest.TestCase):

    def setUp(self) -> None:
        self.sent = []
        self.timers = []
        self.pointer = SimplePointer(self.send, self.timeout_add, delay=1000)

    def send(self, *packet) -> None:
        self.sent.append(packet)

    def timeout_add(self, delay: int, fn) -> None:
        self.timers.append((delay, fn))

    def run_timers(self) -> None:
        timers, self.timers = self.timers, []
        for _delay, fn in timers:
            self.assertFalse(fn())

    def buttons(self) -> list[tuple[int, bool]]:
        return [(packet[4], packet[5]) for packet in self.sent if packet[0] == POINTER_BUTTON]

    def test_split_position(self) -> None:
        self.assertEqual(split_position((-100, 80, -10, 20)), ((-100, 80), {"window-position": (-10, 20)}))

    def test_motion(self) -> None:
        self.pointer.motion(1, POS)
        self.assertEqual(self.sent, [(POINTER_MOTION, -1, 0, 1, (100, 80), {"window-position": (10, 20)})])
        self.sent.clear()
        # too soon: only the latest position is sent, when the timer fires
        self.pointer.motion(1, (101, 80, 11, 20))
        self.pointer.motion(2, (102, 80, 12, 20))
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.timers), 1)
        self.assertLessEqual(self.timers[0][0], 1000)
        self.run_timers()
        self.assertEqual(self.sent, [(POINTER_MOTION, -1, 0, 2, (102, 80), {"window-position": (12, 20)})])

    def test_button_replaces_pending_motion(self) -> None:
        self.pointer.motion(1, POS)
        self.pointer.motion(1, (101, 80, 11, 20))
        self.sent.clear()
        self.pointer.button(1, 1, True, (101, 80, 11, 20))
        self.run_timers()
        self.assertEqual([packet[0] for packet in self.sent], [POINTER_BUTTON])
        self.assertEqual(self.sent[0][6:], ((101, 80), {"window-position": (11, 20)}))

    def test_buttons(self) -> None:
        self.pointer.button(1, 1, True, POS)
        # pressed twice, or released without a press:
        self.pointer.button(1, 1, True, POS)
        self.pointer.button(1, 3, False, POS)
        self.pointer.button(1, 1, False, POS)
        self.pointer.button(1, 1, False, POS)
        self.assertEqual(self.buttons(), [(1, True), (1, False)])

    def test_wheel(self) -> None:
        # up, down twice, right, left, and less than a step:
        for dx, dy in ((0, 1), (0, -2), (1, 0), (-1, 0), (0, 0.25)):
            self.pointer.wheel(1, dx, dy, POS)
        clicks = (4, 5, 5, 7, 6, 4)
        self.assertEqual(self.buttons(), [(b, pressed) for b in clicks for pressed in (True, False)])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
