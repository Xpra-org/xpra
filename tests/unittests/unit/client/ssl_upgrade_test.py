#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ssl
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base.client_base import XpraClientBase
from xpra.net.socket_util import get_ssl_wrap_socket_context
from xpra.util import typedict


class TestSSLUpgrade(unittest.TestCase):

    def upgrade_context(self, socktype, overrides):
        conn = SimpleNamespace(
            socktype=socktype, options={"ssl-options": overrides}, _socket=object(),
            local=("127.0.0.1", 12345), remote=("127.0.0.1", 14500), endpoint="localhost",
        )
        client = XpraClientBase.__new__(XpraClientBase)
        client._protocol = Mock(_conn=conn)
        client._protocol.steal_connection.return_value = conn
        client._protocol.wait_for_io_threads_exit.return_value = True
        client.send = Mock()
        client.setup_connection = Mock()
        wrapped_socket = object()
        with patch("time.sleep"), \
                patch("xpra.net.socket_util.ssl_wrap_socket", return_value=wrapped_socket) as wrap, \
                patch("xpra.net.socket_util.ssl_handshake", return_value=wrapped_socket), \
                patch("xpra.net.bytestreams.SSLSocketConnection") as ssl_conn:
            client.ssl_upgrade(typedict())
        ssl_conn.assert_called_once_with(
            wrapped_socket, conn.local, conn.remote, conn.endpoint,
            {"tcp": "ssl", "ws": "wss"}[socktype],
        )
        client.send.assert_called_once_with("ssl-upgrade", {})
        client.setup_connection.return_value.start.assert_called_once_with()
        return get_ssl_wrap_socket_context(**wrap.call_args[1])[0]

    def test_default_verification(self):
        for socktype in ("tcp", "ws"):
            with self.subTest(socktype=socktype):
                context = self.upgrade_context(socktype, {})
                self.assertEqual(context.verify_mode, ssl.CERT_NONE)
                self.assertFalse(context.check_hostname)

    def test_explicit_verification(self):
        for socktype in ("tcp", "ws"):
            with self.subTest(socktype=socktype):
                context = self.upgrade_context(socktype, {
                    "server-verify-mode": "required",
                    "check-hostname": True,
                    "server-hostname": "example.com",
                })
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(context.check_hostname)


if __name__ == "__main__":
    unittest.main()
