#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xpra.config import vfb


class VFBTest(unittest.TestCase):

    def test_generated_command_parameters(self):
        with patch.object(vfb, "POSIX", True), patch.object(vfb, "OSX", False), \
             patch.object(vfb, "can_use_fakescreenfps", return_value=True), \
             patch.object(vfb, "get_Xdummy_confdir", return_value="supplied-config"):
            for generate in (vfb.get_Xdummy_command, vfb.get_Xvfb_command, vfb.get_Xephyr_command, vfb.get_weston_Xwayland_command):
                with self.subTest(generate=generate.__name__):
                    command = generate(depth=8, dpi=144, fps=30)
                    self.assertEqual(command[command.index("-dpi") + 1], "144x144")
                    self.assertEqual(command[command.index("-fakescreenfps") + 1], "30")
                    self.assertNotIn("Composite", command)

    def test_extension_settings(self):
        with patch.dict(os.environ, {"XPRA_XPRESENT": "1"}), patch.object(vfb, "can_use_fakescreenfps", return_value=False):
            command = vfb.get_Xvfb_command(depth=24)
        self.assertIn("Present", command)
        self.assertNotIn("-fakescreenfps", command)
        self.assertIn("Composite", command)

    def test_command_expansion(self):
        with patch.object(vfb, "get_xorg_bin", return_value="/test/Xorg"), \
             patch.object(vfb, "get_Xdummy_confdir", return_value="supplied-config"), \
             patch.object(vfb, "detect_xvfb_command", return_value=["supplied-auto"]):
            for name, executable in (("Xvfb", "Xvfb"), ("Xephyr", "Xephyr"), ("Xorg", "/test/Xorg"),
                                     ("Xdummy", "/test/Xorg"), ("weston", "/usr/libexec/xpra/xpra_weston_xvfb"),
                                     ("weston+Xwayland", "/usr/libexec/xpra/xpra_weston_xvfb"), ("auto", "supplied-auto")):
                with self.subTest(name=name):
                    self.assertEqual(vfb.xvfb_command(name, depth=0)[0], executable)
            self.assertEqual(vfb.xvfb_command("'/absolute/custom server' --flag"), ["/absolute/custom server", "--flag"])
            self.assertEqual(vfb.xvfb_command("/absolute/server"), ["/absolute/server"])
            self.assertEqual(vfb.xvfb_command("custom-server"), ["custom-server"])

    def test_xorg_search(self):
        with patch.dict(os.environ, {"XPRA_XORG_BIN": "/supplied/Xorg"}):
            self.assertEqual(vfb.get_xorg_bin(), "/supplied/Xorg")
        with patch.dict(os.environ, {"XPRA_XORG_BIN": ""}), patch.object(vfb.os.path, "exists", side_effect=lambda p: p == "/usr/lib/Xorg"):
            self.assertEqual(vfb.get_xorg_bin(), "/usr/lib/Xorg")
        with patch.dict(os.environ, {"XPRA_XORG_BIN": "", "PATH": "/test/bin"}), \
             patch.object(vfb.os.path, "exists", return_value=False), \
             patch.object(vfb.os.path, "isfile", side_effect=lambda p: p == "/test/bin/Xorg"):
            self.assertEqual(vfb.get_xorg_bin(), "/test/bin/Xorg")
        with patch.dict(os.environ, {"XPRA_XORG_BIN": "", "PATH": ""}), \
             patch.object(vfb.os.path, "exists", return_value=False), patch.object(vfb.os.path, "isfile", return_value=False):
            self.assertEqual(vfb.get_xorg_bin(), "")

    def test_xdummy_selection(self):
        with patch.object(vfb, "POSIX", True), patch.object(vfb, "OSX", False), \
             patch.object(vfb, "get_Xdummy_confdir", return_value="supplied-config"):
            for mode, executable in ((0, "/test/Xorg"), (stat.S_ISUID | stat.S_IROTH, "xpra_Xdummy"), (stat.S_ISUID, "Xvfb")):
                with self.subTest(mode=mode), patch.object(vfb, "get_xorg_bin", return_value="/test/Xorg"), \
                     patch.object(vfb.os, "stat", return_value=SimpleNamespace(st_mode=mode)):
                    self.assertEqual(vfb.detect_xdummy_command(warn_fn=lambda msg: None)[0], executable)
            with patch.object(vfb, "get_xorg_bin", return_value=""):
                self.assertEqual(vfb.detect_xdummy_command(warn_fn=lambda msg: None)[0], "xpra_Xdummy")
                self.assertEqual(vfb.detect_xdummy_command(Xdummy_wrapper_ENABLED=False)[0], "Xorg")
            with tempfile.TemporaryDirectory() as folder, patch.object(vfb, "get_xorg_bin", return_value=""):
                (Path(folder) / "xpra_Xdummy").touch()
                with patch.dict(os.environ, {"PATH": "/other"}):
                    self.assertEqual(vfb.detect_xdummy_command(bin_dir=folder, Xdummy_wrapper_ENABLED=True)[0], str(Path(folder) / "xpra_Xdummy"))
                with patch.dict(os.environ, {"PATH": folder}):
                    self.assertEqual(vfb.detect_xdummy_command(bin_dir=folder, Xdummy_wrapper_ENABLED=True)[0], "xpra_Xdummy")
        with patch.object(vfb, "POSIX", False):
            self.assertEqual(vfb.detect_xdummy_command()[0], "Xvfb")

    def test_xvfb_selection(self):
        with patch.object(vfb, "WIN32", False), patch.object(vfb, "OSX", False), \
             patch.object(vfb.sys, "platform", "linux"), patch.object(vfb, "is_DEB", return_value=True), \
             patch.object(vfb, "is_DEB_Xdummy_safe", return_value=False):
            self.assertEqual(vfb.detect_xvfb_command()[0], "Xvfb")
        with patch.object(vfb, "WIN32", False), patch.object(vfb, "OSX", False), \
             patch.object(vfb, "is_DEB", return_value=False), patch.object(vfb.sys, "platform", "linux"), \
             patch("xpra.util.system.get_distribution_version_id", return_value="9"), \
             patch.object(vfb, "detect_xdummy_command", return_value=["supplied-xdummy"]):
            self.assertEqual(vfb.detect_xvfb_command(Xdummy_ENABLED=False)[0], "Xvfb")
            self.assertEqual(vfb.detect_xvfb_command(), ["supplied-xdummy"])
            self.assertEqual(vfb.detect_xvfb_command(Xdummy_ENABLED=True), ["supplied-xdummy"])

    def test_command_wrapping(self):
        self.assertEqual(vfb.wrap_cmd_str([]), "")
        command = ["Xorg", "-config", "a" * 50, "-auth", "b" * 50]
        wrapped = vfb.wrap_cmd_str(command)
        self.assertEqual(command, [])
        self.assertIn("\\\n", wrapped)
        self.assertIn("-config", wrapped)
        self.assertIn("-auth", wrapped)


if __name__ == "__main__":
    unittest.main()
