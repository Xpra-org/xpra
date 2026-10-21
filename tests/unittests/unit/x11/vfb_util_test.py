#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from unittest.mock import patch

from xpra.os_util import POSIX, OSX
from xpra.scripts.config import InitException
from xpra.x11 import vfb_util


class TestVfbUtil(unittest.TestCase):

    def test_check_xorg_config(self):
        with tempfile.NamedTemporaryFile(suffix=".conf") as conf:
            for command in (["Xvfb"], ["Xorg", "-config"], ["Xorg", "-config", "xorg.conf"],
                            ["Xorg", "-config", conf.name]):
                with self.subTest(command=command):
                    vfb_util.check_xorg_config(command)
        with self.assertRaises(InitException):
            vfb_util.check_xorg_config(["Xorg", "-config", conf.name])

    @unittest.skipUnless(POSIX and not OSX, "X11 servers require a POSIX platform")
    def test_missing_config_prevents_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            command = "Xorg -config %s/missing.conf" % directory
            with patch.object(vfb_util, "Popen") as launch:
                with self.assertRaisesRegex(InitException, "configuration file .* not found"):
                    vfb_util.start_Xvfb(command, (), 24, ":100", directory, os.getuid(), os.getgid(), "user")
                launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
