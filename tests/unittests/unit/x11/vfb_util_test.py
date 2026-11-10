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

    @unittest.skipUnless(POSIX, "Xauthority requires a POSIX platform")
    def test_xauthority_uses_target_home(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(vfb_util, "PRIVATE_XAUTH", False), \
                 patch("pwd.getpwnam") as getpwnam:
                getpwnam.return_value.pw_dir = directory
                path = vfb_util.get_xauthority_path(":100", os.getuid(), os.getgid(), "xpra-test-user")
            self.assertEqual(path, os.path.join(directory, ".Xauthority"))

    @unittest.skipUnless(POSIX, "Xauthority requires a POSIX platform")
    def test_xauthority_home_must_be_writable_by_target(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            with patch.object(vfb_util, "PRIVATE_XAUTH", False), \
                 patch.dict(os.environ, {"TMPDIR": directory}, clear=True), \
                 patch("pwd.getpwnam") as getpwnam:
                getpwnam.return_value.pw_dir = os.path.join(directory, "home")
                os.mkdir(getpwnam.return_value.pw_dir, 0o700)
                path = vfb_util.get_xauthority_path(":100", os.getuid() + 1, os.getgid() + 1, "xpra-test-user")
            self.assertEqual(path, os.path.join(directory, ".Xauthority"))

    @unittest.skipUnless(POSIX, "Xauthority requires a POSIX platform")
    def test_xauthority_private_file_names(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(vfb_util, "PRIVATE_XAUTH", True), \
                 patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}):
                for per_display, name in ((True, "Xauthority-100"), (False, "Xauthority")):
                    with patch.object(vfb_util, "XAUTH_PER_DISPLAY", per_display):
                        self.assertEqual(vfb_util.get_xauthority_path(":100"), os.path.join(directory, "xpra", name))

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
