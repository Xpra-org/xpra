#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch


class TestUInputSetup(unittest.TestCase):

    def test_wait_for_input_devices_reads_udev_classification(self):
        from xpra.uinput.setup import wait_for_input_devices
        devices = {"pointer": {"device": "/dev/input/event42"}, "touchpad": {}}
        paths = []

        def open_udev(path, mode):
            paths.append((path, mode))
            return BytesIO(b"E:ID_INPUT=1\nE:ID_INPUT_MOUSE=1\n")

        stat = SimpleNamespace(st_rdev=os.makedev(13, 42))
        with patch("xpra.uinput.setup.os.stat", return_value=stat), \
                patch("xpra.uinput.setup.open", create=True, side_effect=open_udev):
            self.assertTrue(wait_for_input_devices(devices))
        self.assertEqual(paths, [("/run/udev/data/c13:42", "rb")])


if __name__ == "__main__":
    unittest.main()
