#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>

import os
import unittest
from unittest.mock import patch

from xpra.util import env, system


class PlatformIconTest(unittest.TestCase):

    def test_platform_icons(self):
        for platform, expected in (("win32", "win32"), ("darwin", "macos"), ("linux2", "linux"),
                                   ("freebsd14", "freebsd"), ("openbsd7", "openbsd"), ("other", "")):
            with self.subTest(platform=platform):
                self.assertEqual(system.get_platform_icon_name(platform), expected)


class DisplayDetectionTest(unittest.TestCase):

    def test_wayland_environment_precedence(self):
        for values, expected in (({}, False), ({"WAYLAND_DISPLAY": "wayland-0"}, True),
                                 ({"XDG_SESSION_TYPE": "wayland"}, True), ({"GDK_BACKEND": "wayland"}, True),
                                 ({"GDK_BACKEND": "x11", "WAYLAND_DISPLAY": "wayland-0"}, False)):
            with self.subTest(values=values):
                self.assertEqual(system.is_Wayland(values), expected)

    def test_wayland_after_save_env(self):
        with patch.object(env, "_saved_env", {}):
            for backend, expected in (("wayland", True), ("x11", False), ("wayland", True)):
                with self.subTest(backend=backend), patch.dict(os.environ, {"GDK_BACKEND": backend}, clear=True):
                    env.save_env()
                    self.assertEqual(system.is_Wayland(), expected)
                    self.assertFalse(system.is_Wayland({}))


if __name__ == "__main__":
    unittest.main()
