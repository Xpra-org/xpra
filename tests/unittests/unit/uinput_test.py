#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class TestUInputSetup(unittest.TestCase):

    def test_wait_for_input_devices_reads_udev_classification(self):
        from xpra.uinput.setup import wait_for_input_devices
        devices = {"pointer": {"device": "/dev/input/event42"}, "touchpad": {}}
        with patch("xpra.uinput.setup.read_udev_data", return_value=b"E:ID_INPUT=1\nE:ID_INPUT_MOUSE=1\n") as read:
            self.assertTrue(wait_for_input_devices(devices))
        read.assert_called_once_with("/dev/input/event42")

    def test_udev_data_path(self):
        from xpra.uinput.setup import get_udev_data_path
        stat = SimpleNamespace(st_rdev=os.makedev(13, 42))
        with patch("xpra.uinput.setup.os.stat", return_value=stat):
            self.assertEqual(get_udev_data_path("/dev/input/event42"), "/run/udev/data/c13:42")


class TestUInputWheel(unittest.TestCase):

    def setUp(self):
        try:
            from xpra.uinput.device import UInputDevice, MOUSE_WHEEL_CLICK_MULTIPLIER
        except ImportError as e:
            raise unittest.SkipTest(f"no uinput bindings: {e}")
        from uinput import REL_WHEEL, REL_HWHEEL
        self.emitted = []
        device = SimpleNamespace(emit=lambda code, value: self.emitted.append((code, value)))
        self.device = UInputDevice(device, "/dev/input/event42", None)
        self.mult = MOUSE_WHEEL_CLICK_MULTIPLIER
        self.axes = {4: REL_WHEEL, 5: REL_WHEEL, 6: REL_HWHEEL, 7: REL_HWHEEL}
        # positive `REL_WHEEL` is up and positive `REL_HWHEEL` is right:
        self.signs = {4: 1, 5: -1, 6: -1, 7: 1}

    def test_button_owns_direction(self):
        # the client sends the distance signed in the physical direction,
        # and swaps the button when `mousewheel` inverts that axis:
        # the direction must follow the button whatever the sign of the distance
        for button in (4, 5, 6, 7):
            for distance in (1, -1):
                self.emitted.clear()
                self.device.wheel_motion(button, distance)
                self.assertEqual(self.emitted, [(self.axes[button], self.signs[button] * self.mult)],
                                 f"button {button} with distance {distance}")

    def test_click_matches_wheel_motion(self):
        for button in (4, 5, 6, 7):
            self.emitted.clear()
            self.device.click(button, True, {})
            self.device.click(button, False, {})
            self.assertEqual(self.emitted, [(self.axes[button], self.signs[button] * self.mult)], f"button {button}")


if __name__ == "__main__":
    unittest.main()
