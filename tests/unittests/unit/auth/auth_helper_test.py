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

    def _get_bind_auth(self, bind_spec: str):
        # the whole path a "--bind-tcp=HOST:PORT,auth=..." spec goes through:
        # the bind string is parsed first, and whatever comes out of it
        # is what `get_auth_module` has to make sense of
        from xpra.net.socket_util import parse_bind_ip
        sock_options = parse_bind_ip([f"0.0.0.0:10000,{bind_spec}"])[("0.0.0.0", 10000)]
        auth_str = sock_options["auth"]
        self.assertIsInstance(auth_str, str, f"{bind_spec!r} did not parse as a string")
        return self._get(auth_str)

    def test_per_socket_bracket_syntax(self):
        # the preferred syntax: "auth=MODULE(option=value,...)"
        name, _cls, options = self._get_bind_auth("auth=file(filename=pass.txt)")
        self.assertEqual(name, "file")
        self.assertEqual(options.get("filename"), "pass.txt")

    def test_per_socket_bracket_multiple_options(self):
        # the commas inside the brackets must not be mistaken
        # for separators between socket options:
        name, _cls, options = self._get_bind_auth("auth=exec(command=/bin/echo,foo=bar)")
        self.assertEqual(name, "exec")
        self.assertEqual(options.get("command"), "/bin/echo")
        self.assertEqual(options.get("foo"), "bar")

    def test_per_socket_bracket_values_with_equal_signs(self):
        # option values often contain '=': command lines, paths, uris
        name, _cls, options = self._get_bind_auth("auth=exec(command=/bin/foo --arg=1)")
        self.assertEqual(name, "exec")
        self.assertEqual(options.get("command"), "/bin/foo --arg=1")

    def test_per_socket_bracket_with_other_socket_options(self):
        from xpra.net.socket_util import parse_bind_ip
        spec = "0.0.0.0:10000,auth=file(filename=pass.txt),ssl-cert=/tmp/cert.pem"
        sock_options = parse_bind_ip([spec])[("0.0.0.0", 10000)]
        self.assertEqual(sock_options.get("ssl-cert"), "/tmp/cert.pem")
        name, _cls, options = self._get(sock_options["auth"])
        self.assertEqual(name, "file")
        self.assertEqual(options.get("filename"), "pass.txt")

    def test_per_socket_multiple_auth_modules(self):
        from xpra.net.socket_util import parse_bind_ip
        spec = "0.0.0.0:10000,auth=hosts,auth=file(filename=pass.txt)"
        auth_strs = parse_bind_ip([spec])[("0.0.0.0", 10000)]["auth"]
        self.assertEqual(auth_strs, ["hosts", "file(filename=pass.txt)"])
        names = [self._get(auth_str)[0] for auth_str in auth_strs]
        self.assertEqual(names, ["hosts", "file"])

    def test_per_socket_colon_syntax(self):
        # the older "auth=MODULE:option=value" syntax must keep working
        name, _cls, options = self._get_bind_auth("auth=password:value=s3cret")
        self.assertEqual(name, "password")
        self.assertEqual(options.get("value"), "s3cret")

    def test_invalid_type(self):
        from xpra.scripts.config import InitException
        with self.assertRaises(InitException):
            get_auth_module({"password:value": "s3cret"})

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
        _name, _mod, _cls, options = get_auth_module("allow", extra_opt="hello")
        self.assertEqual(options.get("extra_opt"), "hello")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
