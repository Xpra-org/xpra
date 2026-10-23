#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from xpra.config import InitExit
from xpra.exit_codes import ExitCode
from xpra.scripts import parsing


def make_options(**updates):
    values = dict(username="", password="", password_file=[], socket_dirs=["/sockets"],
                  display="original", ssh="ssh -x", exit_ssh=False, remote_xpra=["xpra"],
                  mode="attach", ssl_upgrade="no")
    values.update(updates)
    return SimpleNamespace(**values)


class ConnectionAdapterTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"XPRA_USERNAME": "", "XPRA_PARSING_STRICT": "0", "XPRA_SSH_AGENT": "0"}))
        self.enterContext(patch.multiple(parsing, POSIX=True, WIN32=False, OSX=False))

    def test_complete_tcp_descriptor_and_precedence(self):
        opts = make_options(username="configured", password="configured-password")
        cmdline = ["xpra", "attach"]
        address = "tcp://alice:secret@LOCALHOST:1234/my%20session,encoding=rgb;param?encoding=h264&host=other&tag=a&tag=b#frag"
        with patch.object(parsing, "warn") as warning:
            desc = parsing.parse_display_name(opts, address, cmdline)
        self.assertEqual(desc, {
            "display_name": address, "cmdline": cmdline, "type": "tcp", "username": "alice", "password": "secret",
            "host": "localhost", "local": True, "port": 1234, "encoding": "rgb", "params": "param", "fragment": "frag",
            "display": "my session", "tag": ["a", "b"],
        })
        self.assertIs(desc["cmdline"], cmdline)
        self.assertEqual((opts.username, opts.password, opts.display), ("alice", "secret", "original"))
        self.assertEqual(warning.call_args_list, [
            call("ignoring encoding override from query string"), call("ignoring host override from query string"),
        ])

    def test_credentials_update_before_port_error(self):
        opts = make_options()
        with self.assertRaises(ValueError):
            parsing.parse_display_name(opts, "tcp://alice:secret@host:invalid/10")
        self.assertEqual((opts.username, opts.password, opts.display), ("alice", "secret", "original"))

    def test_password_file_is_lazy(self):
        opts = make_options(password_file=["password-file", "unused"])
        with patch.object(parsing, "load_password_file", return_value="from-file") as load:
            desc = parsing.parse_display_name(opts, "tcp://host/")
            self.assertEqual(desc["password"], "from-file")
            load.assert_called_once_with("password-file")
            parsing.parse_display_name(opts, "tcp://host/")
            self.assertEqual(load.call_count, 1)
            parsing.parse_display_name(opts, "tcp://alice:uri-password@host/")
            self.assertEqual(load.call_count, 1)
        self.assertEqual(opts.password, "uri-password")

    def test_environment_username_and_lookup(self):
        opts = make_options()
        finder = Mock(return_value="tcp://host/10")
        with patch.dict(os.environ, {"XPRA_USERNAME": "environment"}):
            desc = parsing.parse_display_name(opts, "2nd session", find_session_by_name=finder)
        finder.assert_called_once_with(opts, "2nd session")
        self.assertEqual(desc["display_name"], "tcp://host/10")
        self.assertEqual(desc["username"], "environment")
        self.assertEqual(opts.username, "environment")
        with self.assertRaisesRegex(ValueError, "no session found matching name"):
            parsing.parse_display_name(opts, "unknown", find_session_by_name=lambda *_: "")
        with self.assertRaisesRegex(ValueError, "invalid display name"):
            parsing.parse_display_name(opts, "unknown")

    def test_socket_descriptors_and_aliases(self):
        for address, display, extra in (
            (":10", "10", {"socket_dirs": ["/sockets"]}),
            ("wayland-2", "wayland-2", {"socket_dirs": ["/sockets"]}),
            ("@abstract", "abstract", {"socket_path": "@abstract"}),
            ("/tmp/xpra.sock", None, {"socket_dir": "xpra.sock", "socket_dirs": ["/sockets"], "socket_path": "/tmp/xpra.sock"}),
        ):
            with self.subTest(address=address):
                opts = make_options()
                desc = parsing.parse_display_name(opts, address)
                normalized = "socket://" + address if address.startswith("/") else address
                expected = {"display_name": normalized, "cmdline": (), "type": "socket", "local": True, **extra}
                if display is not None:
                    expected["display"] = display
                self.assertEqual(desc, expected)
                self.assertEqual(opts.display, display)
                if "socket_dirs" in desc:
                    self.assertIs(desc["socket_dirs"], opts.socket_dirs)

    def test_local_query_is_applied_before_display(self):
        opts = make_options()
        desc = parsing.parse_display_name(opts, ":10?display=other&local=no")
        self.assertEqual(desc["display"], "10")
        self.assertIs(desc["local"], True)
        self.assertEqual(opts.display, "10")

    def test_abstract_socket_does_not_read_socket_directories(self):
        opts = SimpleNamespace(username="", password="", password_file=[])
        desc = parsing.parse_display_name(opts, "@abstract")
        self.assertEqual(desc["socket_path"], "@abstract")
        self.assertEqual(opts.display, "abstract")

    def test_ssh_complete_descriptor(self):
        opts = make_options()
        cmdline = ["--socket-dirs=/sockets"]
        address = "ssh://alice@host:2222/my%20session"
        desc = parsing.parse_display_name(opts, address, cmdline)
        self.assertEqual(desc, {
            "display_name": address, "cmdline": cmdline, "type": "ssh", "proxy_command": ["_proxy"], "exit_ssh": False,
            "socket_dirs": opts.socket_dirs, "remote_xpra": opts.remote_xpra, "username": "alice", "host": "host",
            "local": False, "port": 2222, "display": "my session", "display_as_args": ["my session"], "agent": False,
            "full_ssh": ["ssh", "-x", "-l", "alice", "-p", "2222", "-T", "host"],
        })
        self.assertIs(desc["socket_dirs"], opts.socket_dirs)
        self.assertIs(desc["remote_xpra"], opts.remote_xpra)
        self.assertEqual(opts.display, "original")

    def test_ssh_socket_directory_requires_explicit_option(self):
        for cmdline in ([], ["--socket-dir", "/sockets"], ["--socket-dirs", "/sockets"],
                        ["--socket-dir=/sockets"], ["--socket-dirs=/sockets"]):
            desc = parsing.parse_display_name(make_options(), "ssh://host/", cmdline)
            self.assertEqual("socket_dirs" in desc, bool(cmdline))

    def test_vnc_ssh_display_arguments(self):
        for display, suffix, port in (("10", "vnc://localhost:5910/", 5910), ("session", "vnc://localhost/", None)):
            desc = parsing.parse_display_name(make_options(), "vnc+ssh://host/" + display)
            self.assertEqual(desc["display_as_args"], [display, suffix])
            self.assertEqual(desc.get("remote_port"), port)

    def test_tls_enrichment_and_upgrade(self):
        for protocol, upgrade, expected in (("ssl", "no", True), ("wss", "no", True), ("quic", "no", True),
                                            ("wt", "no", True), ("tcp", "no", False), ("ws", "no", False),
                                            ("vnc", "yes", True), ("tcp", "auto", True)):
            with self.subTest(protocol=protocol, upgrade=upgrade), \
                    patch.object(parsing, "get_ssl_options", return_value={"resolved": True}) as tls:
                desc = parsing.parse_display_name(make_options(ssl_upgrade=upgrade), protocol + "://host/10")
            self.assertEqual(tls.call_count, int(expected))
            self.assertEqual(desc.get("ssl-options"), {"resolved": True} if expected else None)
            if expected:
                self.assertIs(tls.call_args.args[0], desc)
                self.assertEqual(len(tls.call_args.args), 4 if protocol in ("tcp", "vnc") else 3)

    def test_auto_proxy_fallback_order(self):
        for protocol, alternate in (("tcp", "http"), ("wss", "https")):
            opts = make_options()
            with patch.object(parsing, "get_ssl_options", return_value={}), \
                    patch.object(parsing, "auto_proxy", side_effect=[{}, {"proxy-host": "proxy"}]) as proxy:
                desc = parsing.parse_display_name(opts, protocol + "://host/?proxy=auto")
            self.assertEqual(proxy.call_args_list, [call(protocol, "host"), call(alternate, "host")])
            self.assertEqual(desc["proxy-host"], "proxy")

    def test_platform_errors_precede_credentials(self):
        for address, windows in ((":10", True), ("wayland-0", False), ("@socket", True), ("socket:///tmp/socket", True)):
            with self.subTest(address=address), patch.multiple(parsing, POSIX=False, WIN32=windows, OSX=not windows):
                opts = make_options(password_file=["must-not-read"])
                with patch.object(parsing, "load_password_file") as load, self.assertRaises((RuntimeError, ValueError)):
                    parsing.parse_display_name(opts, address)
                load.assert_not_called()
                self.assertEqual(opts.display, "original")

    def test_named_pipe_forms(self):
        constants = SimpleNamespace(PIPE_PREFIX="Xpra\\", PIPE_ROOT="\\\\")
        for address, pipe, host in (("named-pipe://Main", "Xpra\\Main", ""),
                                    ("named-pipe://./Main", "Xpra\\Main", ""),
                                    ("named-pipe://server/Main", "\\\\server\\pipe\\Xpra\\Main", "server"),
                                    ("named-pipe://127.0.0.1/Main", "\\\\127.0.0.1\\pipe\\Xpra\\Main", "127.0.0.1")):
            with self.subTest(address=address), patch.multiple(parsing, POSIX=False, WIN32=True), \
                    patch.dict(sys.modules, {"xpra.platform.win32.dotxpra": constants}):
                opts = make_options()
                desc = parsing.parse_display_name(opts, address)
            self.assertEqual(desc["named-pipe"], pipe)
            self.assertEqual(desc.get("host", ""), host)
            self.assertEqual(desc["local"], not host)
            self.assertEqual(opts.display, address)

    def test_unknown_transport_preserves_options(self):
        opts = make_options()
        with self.assertRaises(InitExit) as raised:
            parsing.parse_display_name(opts, "unknown://alice:secret@host/")
        self.assertEqual(raised.exception.status, ExitCode.UNSUPPORTED)
        self.assertEqual((opts.username, opts.password, opts.display), ("", "", "original"))


if __name__ == "__main__":
    unittest.main()
