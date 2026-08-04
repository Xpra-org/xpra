#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import subprocess
import sys
import unittest

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
        self.assertTrue(common.gsettings_match(allowlist, "org.gnome.desktop.interface", "gtk-theme"))
        self.assertFalse(common.gsettings_match(allowlist, "org.example.fake", "made-up"))

    def test_parse_option_value(self):
        default = common.GSETTINGS_ALLOWLIST
        # boolean and `auto` values select the default allowlist:
        for value in ("yes", "true", "1", "on", "auto", "AUTO", "", None):
            self.assertEqual(common.parse_gsettings_allowlist(value), default)
        for value in ("no", "false", "0", "off"):
            self.assertEqual(common.parse_gsettings_allowlist(value), ())
        # `auto` can be turned off (ie: on MacOS and MS Windows):
        self.assertEqual(common.parse_gsettings_allowlist("auto", False), ())
        self.assertEqual(common.parse_gsettings_allowlist("yes", False), default)
        # `all` and `*` are aliases for the match-everything pattern:
        for value in ("all", "ALL", " * ", ".*"):
            allowlist = common.parse_gsettings_allowlist(value, False)
            self.assertTrue(common.gsettings_match(allowlist, "org.example.fake", "made-up"))
        # an explicit list of patterns is always honoured,
        # entries without a separator match every key of the matching schemas:
        self.assertEqual(common.parse_gsettings_allowlist("a.b:one, c.d:two ,,e.f", False),
                         (("a.b", "one"), ("c.d", "two"), ("e.f", ".*")))
        # invalid patterns are skipped:
        self.assertEqual(common.parse_gsettings_allowlist("a.b:one,c.d:*oops", False), (("a.b", "one"), ))

    def test_match(self):
        allowlist = (("org\\.gnome\\.desktop\\..*", "font-.*"), ("exact\\.schema", "exact-key"))
        for schema, key in (
            ("org.gnome.desktop.interface", "font-name"),
            ("org.gnome.desktop.interface", "font-hinting"),
            ("exact.schema", "exact-key"),
        ):
            self.assertTrue(common.gsettings_match(allowlist, schema, key))
        for schema, key in (
            # the patterns must match the whole string:
            ("org.gnome.desktop.interface", "no-font-name"),
            ("not.org.gnome.desktop.interface", "font-name"),
            ("exact.schema", "exact-key2"),
            ("org.gnome.desktop.interface", "gtk-theme"),
        ):
            self.assertFalse(common.gsettings_match(allowlist, schema, key))

    def test_env_override(self):
        env = os.environ.copy()
        env["XPRA_GSETTINGS_ALLOWLIST"] = "a.b:one, c.d:two ,,"
        output = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from xpra.net.common import GSETTINGS_ALLOWLIST; print(repr(GSETTINGS_ALLOWLIST))",
            ],
            env=env,
            text=True,
        )
        self.assertEqual(output.strip(), repr((("a.b", "one"), ("c.d", "two"))))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
