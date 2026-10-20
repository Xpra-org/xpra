#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from unittest.mock import patch

from xpra.common import is_x11_property_denied, get_x11_properties_denylist, MAX_X11_PROPERTY_NAME


class X11PropertiesTest(unittest.TestCase):

    def tearDown(self):
        get_x11_properties_denylist.cache_clear()

    def test_default_denylist(self):
        for name in (
            "WM_NAME", "WM_STATE", "WM_CLIENT_LEADER", "SM_CLIENT_ID",
            "_NET_WM_PID", "_NET_WM_STATE", "_NET_STARTUP_ID", "_KDE_NET_WM_BLUR_BEHIND_REGION",
            "_MOTIF_WM_HINTS", "_GTK_THEME_VARIANT", "_XEMBED_INFO", "XdndAware", "XPRA_SERVER",
        ):
            self.assertTrue(is_x11_property_denied(name), name)
        for name in ("_MY_APP_PROPERTY", "PULSE_SERVER", "_NETSCAPE_URL", "MY_WM_"):
            self.assertFalse(is_x11_property_denied(name), name)

    def test_invalid_names(self):
        for name in ("", "A" * (MAX_X11_PROPERTY_NAME + 1), "FOO\x1b[2J", "FOO‮", "éTÉ"):
            self.assertTrue(is_x11_property_denied(name), repr(name))

    def test_env_override(self):
        get_x11_properties_denylist.cache_clear()
        with patch.dict(os.environ, {"XPRA_X11_PROPERTIES_DENYLIST": "_MY_.*,OTHER"}):
            self.assertTrue(is_x11_property_denied("_MY_APP_PROPERTY"))
            self.assertTrue(is_x11_property_denied("OTHER"))
            self.assertFalse(is_x11_property_denied("OTHER_ONE"))
            self.assertFalse(is_x11_property_denied("_KDE_NET_WM_BLUR_BEHIND_REGION"))
        get_x11_properties_denylist.cache_clear()
        with patch.dict(os.environ, {"XPRA_X11_PROPERTIES_DENYLIST": ""}):
            self.assertFalse(is_x11_property_denied("_NET_WM_PID"))
        get_x11_properties_denylist.cache_clear()
        with patch.dict(os.environ, {"XPRA_X11_PROPERTIES_DENYLIST": "[invalid"}):
            self.assertTrue(is_x11_property_denied("_NET_WM_PID"))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
