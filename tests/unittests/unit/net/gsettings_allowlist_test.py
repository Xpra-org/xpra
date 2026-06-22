#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
import importlib

from xpra.util.env import OSEnvContext
from xpra.net import common


class TestGSettingsAllowlist(unittest.TestCase):

    def test_key_roundtrip(self):
        for schema, key in (
            ("org.gnome.desktop.interface", "gtk-theme"),
            ("a.b.c", "some-key"),
            # keys are allowed to contain a separator, schema is not:
            ("schema", "weird:key"),
        ):
            name = common.gsettings_key(schema, key)
            self.assertEqual(name, f"{schema}:{key}")
            self.assertEqual(common.parse_gsettings_key(name), (schema, key))

    def test_parse_invalid_key(self):
        with self.assertRaises(ValueError):
            common.parse_gsettings_key("no-separator-here")

    def test_default_allowlist(self):
        allowlist = common.GSETTINGS_ALLOWLIST
        self.assertTrue(allowlist, "the default allowlist should not be empty")
        # every entry is a (schema, key) pair of non-empty strings:
        for entry in allowlist:
            self.assertEqual(len(entry), 2)
            schema, key = entry
            self.assertTrue(schema and key)
        # a known appearance key is allowlisted, a made-up one is not:
        self.assertIn(("org.gnome.desktop.interface", "gtk-theme"), allowlist)
        self.assertNotIn(("org.example.fake", "made-up"), allowlist)

    def test_env_override(self):
        with OSEnvContext():
            os.environ["XPRA_GSETTINGS_ALLOWLIST"] = "a.b:one, c.d:two ,,garbage-no-colon"
            mod = importlib.reload(common)
            try:
                self.assertEqual(mod.GSETTINGS_ALLOWLIST, (("a.b", "one"), ("c.d", "two")))
            finally:
                # restore the module to its default state for other tests:
                os.environ.pop("XPRA_GSETTINGS_ALLOWLIST", None)
                importlib.reload(common)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
