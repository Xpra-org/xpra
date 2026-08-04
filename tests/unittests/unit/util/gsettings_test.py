#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import subprocess
import sys
import unittest

from xpra.util import gsettings


class TestGSettingsAllowlist(unittest.TestCase):

    def test_parse_option(self):
        allowlist, values = gsettings.parse_gsettings_option(
            "a.b:one,c.d:two=hello(s),org.example:items=['a', 'b'](as)", False,
        )
        self.assertEqual(allowlist, (("a.b", "one"), ))
        self.assertEqual(values, {
            ("c.d", "two"): "hello(s)",
            ("org.example", "items"): "['a', 'b'](as)",
        })
        self.assertEqual(gsettings.split_gsettings_value("(1, 2)((ii))"), ("(1, 2)", "(ii)"))
        self.assertTrue(gsettings.parse_gsettings_option("", True)[0])
        self.assertEqual(gsettings.parse_gsettings_option("", False), ((), {}))
        allowlist, values = gsettings.parse_gsettings_option(
            "none,org.example:key=server-default", True,
        )
        self.assertEqual(allowlist, ())
        self.assertEqual(values, {("org.example", "key"): "server-default"})
        allowlist, values = gsettings.parse_gsettings_option(
            "all,org.example:key=server-default", False,
        )
        self.assertTrue(gsettings.gsettings_match(allowlist, "any.schema", "any-key"))
        self.assertEqual(values, {("org.example", "key"): "server-default"})

    def test_key_roundtrip(self):
        for schema, key in (
            ("org.gnome.desktop.interface", "gtk-theme"),
            ("a.b.c", "some-key"),
            # keys are allowed to contain a separator, schema is not:
            ("schema", "weird:key"),
        ):
            name = gsettings.gsettings_key(schema, key)
            self.assertEqual(name, f"{schema}:{key}")
            self.assertEqual(gsettings.parse_gsettings_key(name), (schema, key))

    def test_parse_invalid_key(self):
        with self.assertRaises(ValueError):
            gsettings.parse_gsettings_key("no-separator-here")

    def test_default_allowlist(self):
        allowlist = gsettings.GSETTINGS_ALLOWLIST
        self.assertTrue(allowlist, "the default allowlist should not be empty")
        # every entry is a (schema, key) pair of non-empty strings:
        for entry in allowlist:
            self.assertEqual(len(entry), 2)
            schema, key = entry
            self.assertTrue(schema and key)
        # a known appearance key is allowlisted, a made-up one is not:
        self.assertTrue(gsettings.gsettings_match(allowlist, "org.gnome.desktop.interface", "gtk-theme"))
        self.assertFalse(gsettings.gsettings_match(allowlist, "org.example.fake", "made-up"))

    def test_parse_option_value(self):
        default = gsettings.GSETTINGS_ALLOWLIST
        # boolean and `auto` values select the default allowlist:
        for value in ("yes", "true", "1", "on", "auto", "AUTO", "", None):
            self.assertEqual(gsettings.parse_gsettings_allowlist(value), default)
        for value in ("no", "false", "0", "off"):
            self.assertEqual(gsettings.parse_gsettings_allowlist(value), ())
        # `auto` can be turned off (ie: on MacOS and MS Windows):
        self.assertEqual(gsettings.parse_gsettings_allowlist("auto", False), ())
        self.assertEqual(gsettings.parse_gsettings_allowlist("yes", False), default)
        # Boolean policy tokens are recognized within a CSV list:
        self.assertEqual(gsettings.parse_gsettings_allowlist("none,a.b:one", True), ())
        self.assertEqual(gsettings.parse_gsettings_allowlist("all,a.b:one", False),
                         ((gsettings.ALL_GSETTINGS_PATTERN, gsettings.ALL_GSETTINGS_PATTERN), ))
        combined = gsettings.parse_gsettings_allowlist("yes,a.b:one", False)
        self.assertTrue(gsettings.gsettings_match(combined, "a.b", "one"))
        self.assertTrue(gsettings.gsettings_match(combined, "org.gnome.desktop.interface", "gtk-theme"))
        # `all` and `*` are aliases for the match-everything pattern:
        for value in ("all", "ALL", " * ", ".*"):
            allowlist = gsettings.parse_gsettings_allowlist(value, False)
            self.assertTrue(gsettings.gsettings_match(allowlist, "org.example.fake", "made-up"))
        # an explicit list of patterns is always honoured,
        # entries without a separator match every key of the matching schemas:
        self.assertEqual(gsettings.parse_gsettings_allowlist("a.b:one, c.d:two ,,e.f", False),
                         (("a.b", "one"), ("c.d", "two"), ("e.f", ".*")))
        # invalid patterns are skipped:
        self.assertEqual(gsettings.parse_gsettings_allowlist("a.b:one,c.d:*oops", False), (("a.b", "one"), ))

    def test_match(self):
        allowlist = (("org\\.gnome\\.desktop\\..*", "font-.*"), ("exact\\.schema", "exact-key"))
        for schema, key in (
            ("org.gnome.desktop.interface", "font-name"),
            ("org.gnome.desktop.interface", "font-hinting"),
            ("exact.schema", "exact-key"),
        ):
            self.assertTrue(gsettings.gsettings_match(allowlist, schema, key))
        for schema, key in (
            # the patterns must match the whole string:
            ("org.gnome.desktop.interface", "no-font-name"),
            ("not.org.gnome.desktop.interface", "font-name"),
            ("exact.schema", "exact-key2"),
            ("org.gnome.desktop.interface", "gtk-theme"),
        ):
            self.assertFalse(gsettings.gsettings_match(allowlist, schema, key))

    def test_env_override(self):
        env = os.environ.copy()
        env["XPRA_GSETTINGS_ALLOWLIST"] = "a.b:one, c.d:two ,,"
        output = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from xpra.util.gsettings import GSETTINGS_ALLOWLIST; print(repr(GSETTINGS_ALLOWLIST))",
            ],
            env=env,
            text=True,
        )
        self.assertEqual(output.strip(), repr((("a.b", "one"), ("c.d", "two"))))

    def test_parse_client_values(self):
        values = {
            "Adwaita(s)": ("s", "'Adwaita'"),
            "true(bool)": ("b", "true"),
            "12(u)": ("u", "uint32 12"),
            "['one', 'two'](as)": ("as", "['one', 'two']"),
            "(1, 2)((ii))": ("(ii)", "(1, 2)"),
            # Canonical GVariant text from existing clients remains supported:
            "'Yaru'": ("s", "'Yaru'"),
        }
        for text, (variant_type, canonical) in values.items():
            with self.subTest(text=text):
                variant = gsettings.parse_gsettings_value(text)
                self.assertIsNotNone(variant)
                self.assertEqual(variant.get_type_string(), variant_type)
                self.assertEqual(variant.print_(True), canonical)
        inferred = gsettings.parse_gsettings_value("Adwaita", "s")
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred.print_(True), "'Adwaita'")
        inferred = gsettings.parse_gsettings_value("12", "u")
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred.print_(True), "uint32 12")

    def test_invalid_client_values(self):
        for text in ("missing-type", "value()", "value(not-a-type)", "abc(i)"):
            with self.subTest(text=text):
                self.assertIsNone(gsettings.parse_gsettings_value(text))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
