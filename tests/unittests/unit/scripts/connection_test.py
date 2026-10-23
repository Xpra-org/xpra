#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from urllib import parse

from xpra.config import InitException
from xpra.scripts import connection


class ConnectionGrammarTest(unittest.TestCase):
    def test_normalization(self):
        for address, expected in (
            ("@abstract", "@abstract"), ("/tmp/socket", "socket:///tmp/socket"), ("10.0", ":10.0"),
            ("2nd session", "2nd session"), ("xpra+tcp://host/10", "tcp://host/10"),
            ("tcp://user@fe80::1:10000/", "tcp://user@[fe80::1]:10000/"),
            ("tcp://[::1]:10000/", "tcp://[::1]:10000/"), ("socket:///tmp/socket", "socket:///tmp/socket"),
            ("vsock://10:any/path", "vsock://10:0/path"), ("vsock://10:AUTO", "vsock://10:0/"),
            ("vsock://10:2000", "vsock://10:2000"), ("tcp://[broken", "tcp://[broken"),
        ):
            with self.subTest(address=address):
                self.assertEqual(connection.normalize_display_name(address, posix=True, windows=False, osx=False), expected)
        self.assertEqual(connection.normalize_display_name("Main", posix=False, windows=True, osx=False, pipe_prefix="Xpra\\"),
                         "named-pipe://Xpra\\Main")
        self.assertEqual(connection.normalize_display_name("10", posix=False, windows=False, osx=True), "10")
        with self.assertRaisesRegex(ValueError, "no display name"):
            connection.normalize_display_name("", posix=True, windows=False, osx=False)

    def test_url_policy_and_typed_values(self):
        warning = Mock()
        address, options = connection.parse_URL("xpra+tcp://host:10000/10?encoding=rgb&quality=75&start=bad", warn=warning)
        self.assertEqual(address, "tcp://host:10000//10")
        self.assertEqual(options, {"encoding": "rgb", "quality": 75})
        warning.assert_called_once_with("Warning: option 'start' is not allowed in URLs and will be ignored")
        self.assertEqual(connection.parse_URL("tcp://host/?quality=75", "strict", warn=Mock())[1], {})
        for policy in ("no", "invalid"):
            with self.assertRaises(InitException):
                connection.parse_URL("tcp://host/", policy)
        self.assertEqual(connection.parse_URL("socket:///tmp/socket"), ("//tmp/socket", {}))
        self.assertEqual(connection.parse_URL("tcp://host/"), ("tcp://host//", {}))
        self.assertEqual(connection.parse_URL("tcp://host"), ("tcp://host", {}))
        with patch.dict(connection.OPTION_TYPES, {"encoding": list}):
            self.assertEqual(connection.parse_URL("tcp://host/?encoding=rgb&encoding=h264")[1], {"encoding": ["rgb", "h264"]})

    def test_parameters_independent_of_scheme_registration(self):
        for schemes in ([], ["tcp"]):
            with patch.object(parse, "uses_params", schemes):
                parsed = connection.parse_connection_url("tcp://host/a;b/c;params?key=value#fragment")
            self.assertEqual((parsed.path, parsed.params, parsed.query, parsed.fragment), ("/a;b/c", "params", "key=value", "fragment"))
        with patch.object(parse, "uses_params", []):
            self.assertEqual(connection.parse_connection_url("tcp://host/a;b/c").path, "/a;b/c")
        self.assertEqual(connection.parse_connection_url("unknown://host/a;b").path, "/a;b")

    def test_host_and_port(self):
        for address, default, expected in (
            ("tcp:///", 10000, {"host": "127.0.0.1", "local": True, "port": 10000}),
            ("ssh://host/", 0, {"host": "host", "local": False}),
            ("ssh://[::1]:2222/", 0, {"host": "::1", "local": True, "port": 2222}),
        ):
            self.assertEqual(connection.get_host_port(connection.parse_connection_url(address), default), expected)
        for port in ("bad", "-1", "65536"):
            with self.assertRaises(ValueError):
                connection.get_host_port(connection.parse_connection_url(f"tcp://host:{port}/"), 10000)

    def test_path_and_query_precedence(self):
        parsed = connection.parse_connection_url("ssh://host/name%2Cwith%3Dequals,encoding=rgb;params?encoding=h264&tag=a&tag=b#fragment")
        desc = {"host": "host"}
        warning = Mock()

        def query(value):
            connection.add_query(desc, parsed, value, strict=False, warn=warning)

        connection.add_path(desc, parsed.path, query)
        query(parsed.query)
        self.assertEqual(desc, {"host": "host", "display": "name,with=equals", "encoding": "rgb",
                                "params": "params", "fragment": "fragment", "tag": ["a", "b"]})
        warning.assert_called_once_with("ignoring encoding override from query string")
        for path, expected in (("/encoding=rgb", {}), ("", {}), ("/plain", {"display": "plain"})):
            desc = {}
            callback = Mock()
            connection.add_path(desc, path, callback)
            self.assertEqual(desc, expected)
            self.assertEqual(callback.call_count, int("=" in path))

    def test_strict_connection_query(self):
        parsed = connection.parse_connection_url("tcp://host/?proxy-host=other&quality=50&empty=")
        desc = {}
        warning = Mock()
        connection.add_query(desc, parsed, parsed.query, strict=True, warn=warning)
        self.assertEqual(desc, {"quality": "50"})
        self.assertEqual(warning.call_count, 1)

    def test_socket_fields_and_named_pipes(self):
        dirs = ["/sockets"]
        parsed = connection.parse_connection_url(":10")
        self.assertEqual(connection.get_local_display_attributes(":10", parsed, []), {"type": "socket", "local": True, "display": "10"})
        self.assertIs(connection.get_local_display_attributes(":10", parsed, dirs)["socket_dirs"], dirs)
        for address, expected in (("named-pipe://Main", "Xpra\\Main"), ("named-pipe://Xpra\\Main", "Xpra\\Main"),
                                  ("named-pipe://./Main", "Xpra\\Main"),
                                  ("named-pipe://server/Main", "\\\\server\\pipe\\Xpra\\Main"),
                                  ("named-pipe://\\\\server\\pipe\\Xpra\\Main", "\\\\server\\pipe\\Xpra\\Main"),
                                  ("named-pipe://\\\\.\\pipe\\Xpra\\Main", "\\\\.\\pipe\\Xpra\\Main"),
                                  ("named-pipe://\\", "\\\\")):
            with self.subTest(address=address):
                fields = connection.get_named_pipe_attributes(connection.parse_connection_url(address), "Xpra\\", "\\\\")
                self.assertEqual(fields["named-pipe"], expected)

    def test_ssh_display_argument_alias(self):
        args = ["provided"]
        desc = {"display": "10", "display_as_args": args}
        self.assertIs(connection.get_ssh_display_args(desc, "vnc+ssh"), args)
        self.assertEqual(args, ["provided", "vnc://localhost:5910/"])
        self.assertEqual(connection.get_ssh_display_args({}, "ssh"), [])

    def test_hyperv_services(self):
        self.assertEqual(connection.parse_hyperv_serviceid(20000), "00004e20-facb-11e6-bd58-64006a7986d3")
        uuid = "00112233-4455-6677-8899-aabbccddeeff"
        self.assertEqual(connection.parse_hyperv_serviceid(uuid.upper()), uuid)
        for value, message in (("bad", "not numeric"), (-1, "out of range"), (65536, "out of range"),
                               ("not-a-uuid", "not a valid uuid")):
            with self.assertRaisesRegex(ValueError, message):
                connection.parse_hyperv_serviceid(value)

    def test_import_without_transports_or_cli(self):
        code = '''
import sys
from xpra.scripts.connection import parse_connection_url, get_host_port
assert get_host_port(parse_connection_url("tcp://host:1234/"), 10000)["port"] == 1234
blocked = ("paramiko", "asyncssh", "ssl", "gi", "xpra.scripts.parsing", "xpra.net.tls", "xpra.net.vsock")
assert not [name for name in sys.modules if any(name == p or name.startswith(p + ".") for p in blocked)]
'''
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
