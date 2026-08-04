#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.os_util import WIN32


class PlatformGSettingsTest(unittest.TestCase):

    def test_macos_values(self):
        from xpra.platform.darwin import gsettings
        with (
            patch.object(gsettings, "_uses_dark_theme", return_value=True),
            patch.object(gsettings, "_uses_high_contrast", return_value=False),
        ):
            self.assertEqual(gsettings.get_auto_gsettings(), {
                ("org.gnome.desktop.wm.preferences", "button-layout"):
                    "'close,minimize,maximize:'",
                ("org.gnome.desktop.interface", "color-scheme"): "'prefer-dark'",
                ("org.gnome.desktop.a11y.interface", "high-contrast"): "false",
            })

    @unittest.skipUnless(WIN32, "requires MS Windows")
    def test_windows_values(self):
        from xpra.platform.win32 import gsettings
        with (
            patch.object(gsettings, "_uses_dark_theme", return_value=False),
            patch.object(gsettings, "_uses_high_contrast", return_value=True),
        ):
            self.assertEqual(gsettings.get_auto_gsettings(), {
                ("org.gnome.desktop.wm.preferences", "button-layout"):
                    "':minimize,maximize,close'",
                ("org.gnome.desktop.interface", "color-scheme"): "'default'",
                ("org.gnome.desktop.a11y.interface", "high-contrast"): "true",
            })


def main():
    unittest.main()


if __name__ == "__main__":
    main()
