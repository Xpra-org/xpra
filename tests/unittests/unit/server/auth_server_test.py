#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import MagicMock


def make_server():
    """Return an AuthenticatedServer instance wired up with minimal stubs."""
    from xpra.server.auth import AuthenticatedServer

    class ConcreteServer(AuthenticatedServer):
        def call_hello_oked(self, proto, c, auth_caps):
            pass

        # stubs required by StubServerMixin / ServerCore interface
        def disconnect_client(self, proto, msg):
            pass

        def schedule_verify_connection_accepted(self, proto, timeout):
            pass

        def cancel_verify_connection_accepted(self, proto):
            pass

        def handle_command_request(self, proto, *args):
            pass

        @property
        def _socket_dirs(self):
            return []

    s = ConcreteServer()
    return s


class TestGetAuthModules(unittest.TestCase):

    def test_empty_list(self):
        s = make_server()
        result = s.get_auth_modules("tcp", [])
        assert result == ()

    def test_none_auth(self):
        s = make_server()
        result = s.get_auth_modules("tcp", ["none"])
        assert len(result) == 1
        name, _, cls, opts = result[0]
        assert "none" in name.lower()

    def test_allow_auth(self):
        s = make_server()
        result = s.get_auth_modules("tcp", ["allow"])
        assert len(result) == 1
        name, _, cls, opts = result[0]
        assert "allow" in name.lower()

    def test_reject_auth(self):
        s = make_server()
        result = s.get_auth_modules("tcp", ["reject"])
        assert len(result) == 1
        name, _, cls, opts = result[0]
        assert "reject" in name.lower()

    def test_multiple_auth_modules(self):
        s = make_server()
        result = s.get_auth_modules("tcp", ["none", "allow"])
        assert len(result) == 2

    def test_invalid_module_raises(self):
        s = make_server()
        with self.assertRaises(Exception):
            s.get_auth_modules("tcp", ["does-not-exist-xpra-test-module"])


class TestMakeAuthenticators(unittest.TestCase):

    def _make_conn(self, socktype="tcp", auth=""):
        conn = MagicMock()
        conn.socktype = socktype
        conn.socktype_wrapped = socktype
        conn.options = {}
        if auth:
            conn.options["auth"] = auth
        return conn

    def test_none_auth(self):
        s = make_server()
        # pre-populate auth_classes as init_auth would
        s.auth_classes["tcp"] = s.get_auth_modules("tcp", ["none"])
        conn = self._make_conn("tcp")
        auths = s.make_authenticators("tcp", {}, conn)
        assert len(auths) == 1
        assert not auths[0].requires_challenge()

    def test_allow_auth(self):
        s = make_server()
        s.auth_classes["tcp"] = s.get_auth_modules("tcp", ["allow"])
        conn = self._make_conn("tcp")
        auths = s.make_authenticators("tcp", {}, conn)
        assert len(auths) == 1
        assert auths[0].requires_challenge()

    def test_empty_auth_list(self):
        s = make_server()
        s.auth_classes["tcp"] = ()
        conn = self._make_conn("tcp")
        auths = s.make_authenticators("tcp", {}, conn)
        assert auths == ()

    def test_per_socket_auth_override(self):
        # per-socket auth= in conn.options overrides the global class list
        s = make_server()
        s.auth_classes["tcp"] = s.get_auth_modules("tcp", ["reject"])
        conn = self._make_conn("tcp", auth="none")
        auths = s.make_authenticators("tcp", {}, conn)
        assert len(auths) == 1
        assert not auths[0].requires_challenge()

    def test_unknown_socktype_raises(self):
        s = make_server()
        conn = self._make_conn("unknown-type")
        with self.assertRaises(RuntimeError):
            s.make_authenticators("unknown-type", {}, conn)

    def test_illegal_option_self_raises(self):
        s = make_server()
        conn = self._make_conn("tcp")
        conn.options = {"self": "injected"}
        s.auth_classes["tcp"] = s.get_auth_modules("tcp", ["none"])
        with self.assertRaises((ValueError, Exception)):
            s.make_authenticators("tcp", {}, conn)


def _make_fake_opts(**extra):
    """Minimal opts object with all socket-type auth attributes set to ['none']."""
    class FakeOpts:
        # used for 'socket' and 'named-pipe'
        auth = ["none"]
        # one attribute per non-skipped, non-local socket type
        tcp_auth = ["none"]
        ws_auth = ["none"]
        wss_auth = ["none"]
        ssl_auth = ["none"]
        ssh_auth = ["none"]
        rfb_auth = ["none"]
        vsock_auth = ["none"]
        quic_auth = ["none"]

    for k, v in extra.items():
        setattr(FakeOpts, k, v)
    return FakeOpts()


class TestInitAuth(unittest.TestCase):

    def test_init_auth_populates_classes(self):
        s = make_server()
        s.init_auth(_make_fake_opts())
        assert "tcp" in s.auth_classes
        assert "ssl" in s.auth_classes
        # socket / named-pipe map to the generic auth
        assert "socket" in s.auth_classes

    def test_init_sets_password_file(self):
        s = make_server()
        opts = _make_fake_opts(password_file=["/tmp/test-pass.txt"])
        s.init(opts)
        assert s.password_file == ["/tmp/test-pass.txt"]


def main():
    unittest.main()


if __name__ == '__main__':
    main()
