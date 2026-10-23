#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from xpra.config import InitException, InitExit, InitInfo
from xpra.config.types import OPTION_TYPES, XpraConfig, dict_to_config, name_to_field, remove_dupes
from xpra.config.validation import validate_config, parse_landlock_option, split_landlock_option


class ConfigTypesTest(unittest.TestCase):

    def test_value_conversion_and_clone(self):
        values = {"session-name": "test", "start-child": ["xterm"]}
        options = dict_to_config(values)
        self.assertIsInstance(options, XpraConfig)
        self.assertEqual(options.session_name, "test")
        cloned = options.clone()
        cloned.session_name = "clone"
        self.assertEqual(options.session_name, "test")
        self.assertIs(cloned.start_child, options.start_child)
        self.assertEqual(name_to_field("compression_level"), "compression_level")
        self.assertIn("session_name", repr(options))

    def test_duplicate_order(self):
        self.assertEqual(remove_dupes(x for x in ("b", "a", "b", "c", "a")), ["b", "a", "c"])

    def test_compatibility_identities(self):
        from xpra.scripts import config as legacy
        self.assertIs(legacy.InitException, InitException)
        self.assertIs(legacy.InitExit, InitExit)
        self.assertIs(legacy.InitInfo, InitInfo)
        self.assertIs(legacy.XpraConfig, XpraConfig)
        self.assertIs(legacy.OPTION_TYPES, OPTION_TYPES)
        error = InitExit(7, "message")
        self.assertEqual(error.status, 7)
        self.assertEqual(str(error), "message")

    def test_imports_do_not_discover_defaults(self):
        script = """
import sys
import xpra.config.types
import xpra.config.validation
for name in ('xpra.config.defaults', 'xpra.config.io', 'xpra.config.vfb', 'xpra.scripts.config', 'gi', 'xpra.audio'):
    assert name not in sys.modules, name
"""
        result = subprocess.run([sys.executable, "-S", "-c", script], env=os.environ.copy(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ValidationTest(unittest.TestCase):

    def test_supplied_values(self):
        self.assertEqual(validate_config({"title": "test", "quality": "75", "video": "yes", "auto-refresh-delay": "0.25",
                                          "start": "xterm"}),
                         {"title": "test", "quality": 75, "video": True, "auto-refresh-delay": 0.25, "start": ["xterm"]})

    def test_rejected_values_and_diagnostics(self):
        with patch("xpra.config.warn") as warn:
            result = validate_config({"unknown": "x", "daemon": "yes", "title": 1, "start": ("xterm",), "video": "auto"})
        self.assertEqual(result, {})
        self.assertEqual(warn.call_count, 4)

    def test_lists_and_none(self):
        commands = ["xterm", "terminal"]
        self.assertIs(validate_config({"start": commands})["start"], commands)
        self.assertEqual(validate_config({"start": None}), {"start": None})
        self.assertEqual(validate_config(), {})

    def test_extra_types_and_validation(self):
        with patch("xpra.config.warn") as warn:
            result = validate_config({"extra": "12", "title": "bad", "start": None},
                                     extras_types={"extra": int},
                                     extras_validation={"title": lambda value: "rejected", "start": lambda value: self.fail("validated None")})
        self.assertEqual(result, {"extra": 12, "start": None})
        warn.assert_called_once()
        self.assertNotIn("extra", OPTION_TYPES)

    def test_file_restrictions_are_supplied(self):
        self.assertEqual(validate_config({"daemon": "yes"}, discard=()), {"daemon": True})

    def test_invalid_numbers(self):
        for name in ("quality", "auto-refresh-delay"):
            with self.subTest(name=name):
                self.assertEqual(validate_config({name: "invalid"}), {name: 0})

    def test_landlock_policy(self):
        for value, expected in ((False, "no"), (True, "default"), (" STRICT + GPU ", "strict+gpu"), ("yes+gpu", "default+gpu")):
            with self.subTest(value=value):
                self.assertEqual(parse_landlock_option(value), expected)
                self.assertEqual(split_landlock_option(value), (expected.split("+")[0], "+" in expected))
        for value in ("invalid", "no+gpu", "strict+invalid", "strict+"):
            with self.subTest(value=value), self.assertRaises(InitException):
                parse_landlock_option(value)


if __name__ == "__main__":
    unittest.main()
