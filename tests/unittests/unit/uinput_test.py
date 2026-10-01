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


if __name__ == "__main__":
    unittest.main()
