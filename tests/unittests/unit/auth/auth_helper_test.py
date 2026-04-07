#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.auth.auth_helper import get_auth_module


class TestGetAuthModule(unittest.TestCase):

    def _get(self, auth_str, **kwargs):
        name, _mod, cls, options = get_auth_module(auth_str, **kwargs)
        return name, cls, options

    def test_simple_name(self):
        name, cls, options = self._get("allow")
        self.assertEqual(name, "allow")
        self.assertTrue(callable(cls))
        self.assertNotIn("command", options)

    def test_colon_options(self):
        name, cls, options = self._get("file:filename=pass.txt")
        self.assertEqual(name, "file")
        self.assertEqual(options.get("filename"), "pass.txt")

    def test_comma_options(self):
        # legacy comma separator
        name, cls, options = self._get("env,name=MYPASSWD")
        self.assertEqual(name, "env")
        self.assertEqual(options.get("name"), "MYPASSWD")

    def test_bracket_syntax(self):
        name, cls, options = self._get("exec(command=/bin/echo)")
        self.assertEqual(name, "exec")
        self.assertEqual(options.get("command"), "/bin/echo")

    def test_bracket_multiple_options(self):
        name, cls, options = self._get("exec(command=/bin/echo,foo=bar)")
        self.assertEqual(name, "exec")
        self.assertEqual(options.get("command"), "/bin/echo")
        self.assertEqual(options.get("foo"), "bar")

    def test_bracket_with_commas_in_value(self):
        # commas inside brackets belong to the auth options, not the bind string
        name, cls, options = self._get("exec(command=/bin/echo,display=auto)")
        self.assertEqual(name, "exec")
        self.assertEqual(options.get("display"), "auto")

    def test_invalid_name_base(self):
        with self.assertRaises(ValueError):
            get_auth_module("sys_auth_base")

    def test_invalid_name_helper(self):
        with self.assertRaises(ValueError):
            get_auth_module("auth_helper")

    def test_invalid_module(self):
        from xpra.scripts.config import InitException
        with self.assertRaises(InitException):
            get_auth_module("nonexistent_module_xyz")

    def test_kwargs_passed_through(self):
        _name, _cls, options = get_auth_module("allow", extra_opt="hello")
        self.assertEqual(options.get("extra_opt"), "hello")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
