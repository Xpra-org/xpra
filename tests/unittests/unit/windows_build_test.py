#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class WindowsBuildTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[3] / "packaging" / "MSWindows" / "BUILD.py"
        spec = importlib.util.spec_from_file_location("xpra_windows_build", str(path))
        cls.build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.build)
        path = Path(__file__).resolve().parents[3] / "fs" / "bin" / "add_build_info.py"
        spec = importlib.util.spec_from_file_location("xpra_add_build_info", str(path))
        cls.build_info = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.build_info)

    def test_boolean_options_and_defaults(self):
        args, unknown = self.build.parse_command_line([])
        self.assertFalse(args.verbose)
        self.assertTrue(args.build)
        self.assertFalse(args.service)
        self.assertEqual(unknown, [])
        for argv, expected in ((["--no-build"], False), (["--no-build", "--build"], True),
                               (["--build", "--no-build"], False)):
            with self.subTest(argv=argv):
                args, unknown = self.build.parse_command_line(argv)
                self.assertEqual(args.build, expected)
                self.assertEqual(unknown, [])
        args, unknown = self.build.parse_command_line(["--no-light", "--no-zip-modules", "--desktop-logon"])
        self.assertFalse(args.zip_modules)
        self.assertTrue(args.desktop_logon)
        self.assertEqual(unknown, [])

    def test_command_output_uses_compatible_text_mode(self):
        local_command = self.build.os.path.abspath("./link.exe")

        def command_output(_cmd, **kwargs):
            return subprocess.check_output([sys.executable, "-c", "print('tool.exe')"], **kwargs)

        with patch.object(self.build.os.path, "exists", side_effect=lambda path: path != local_command), \
                patch.object(self.build, "check_output", side_effect=command_output):
            self.assertEqual(self.build.find_vs_command("link"), "tool.exe")

    def test_windows_platform_output_uses_compatible_subprocess_options(self):
        def command_output(_cmd, **kwargs):
            return subprocess.run([sys.executable, "-c", "print('Microsoft Windows')"], **kwargs)

        with patch.object(self.build_info.sys, "platform", "win32"), \
                patch.object(self.build_info, "run", side_effect=command_output):
            self.assertEqual(self.build_info.get_platform_name(), "Microsoft Windows")


if __name__ == "__main__":
    unittest.main()
