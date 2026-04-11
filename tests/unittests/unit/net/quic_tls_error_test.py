#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: Tests for QUIC TLS error surfacing — verifies that TLS errors during
# ABOUTME: QUIC handshake are caught and formatted as actionable user messages.

import asyncio
import unittest
from unittest.mock import patch

from xpra.exit_codes import ExitCode


class TestFormatTLSError(unittest.TestCase):
    """Test that TLS/OpenSSL exceptions are mapped to user-friendly messages."""

    def test_openssl_no_such_file(self):
        from xpra.net.quic.client import format_tls_error
        # simulate the OpenSSL error from a missing CA bundle
        try:
            from OpenSSL.crypto import Error as OpenSSLError
        except ImportError:
            raise unittest.SkipTest("pyOpenSSL not available")
        err = OpenSSLError([
            ("system library", "", ""),
            ("BIO routines", "", "no such file"),
            ("x509 certificate routines", "", "BIO lib"),
        ])
        exit_code, msg = format_tls_error(err)
        self.assertEqual(exit_code, ExitCode.SSL_FAILURE)
        self.assertIn("CA certificate", msg)

    def test_openssl_certificate_verify_failed(self):
        from xpra.net.quic.client import format_tls_error
        try:
            from OpenSSL.crypto import Error as OpenSSLError
        except ImportError:
            raise unittest.SkipTest("pyOpenSSL not available")
        err = OpenSSLError([
            ("x509 certificate routines", "", "certificate verify failed"),
        ])
        exit_code, msg = format_tls_error(err)
        self.assertEqual(exit_code, ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE)
        self.assertIn("certificate verify failed", msg.lower())

    def test_openssl_hostname_mismatch(self):
        from xpra.net.quic.client import format_tls_error
        try:
            from OpenSSL.crypto import Error as OpenSSLError
        except ImportError:
            raise unittest.SkipTest("pyOpenSSL not available")
        err = OpenSSLError([
            ("x509 certificate routines", "", "hostname mismatch"),
        ])
        exit_code, msg = format_tls_error(err)
        self.assertEqual(exit_code, ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE)
        self.assertIn("hostname mismatch", msg.lower())

    def test_connection_error_no_message(self):
        from xpra.net.quic.client import format_tls_error
        err = ConnectionError()
        exit_code, msg = format_tls_error(err)
        self.assertEqual(exit_code, ExitCode.SSL_FAILURE)
        self.assertIn("handshake", msg.lower())

    def test_generic_exception(self):
        from xpra.net.quic.client import format_tls_error
        err = RuntimeError("something went wrong")
        exit_code, msg = format_tls_error(err)
        self.assertEqual(exit_code, ExitCode.SSL_FAILURE)
        self.assertIn("something went wrong", msg)


class TestDatagramReceivedErrorCapture(unittest.TestCase):
    """Test that WebSocketClient.datagram_received catches TLS errors."""

    def _make_protocol(self):
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.connection import QuicConnection
        from aioquic.h3.connection import H3_ALPN
        from xpra.net.quic.client import WebSocketClient
        config = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)
        conn = QuicConnection(configuration=config)
        return WebSocketClient(conn)

    def test_tls_error_stored_on_protocol(self):
        """When datagram_received raises, the error is stored on _tls_error."""
        protocol = self._make_protocol()
        try:
            from OpenSSL.crypto import Error as OpenSSLError
        except ImportError:
            raise unittest.SkipTest("pyOpenSSL not available")
        tls_err = OpenSSLError([("x509 certificate routines", "", "certificate verify failed")])
        # patch the parent datagram_received to simulate a TLS error
        with patch.object(type(protocol).__mro__[1], "datagram_received", side_effect=tls_err):
            protocol.datagram_received(b"\x00" * 10, ("127.0.0.1", 10000))
        self.assertIs(protocol._tls_error, tls_err)

    def test_connected_waiter_resolved_with_error(self):
        """When datagram_received raises and a waiter exists, it gets the error."""
        protocol = self._make_protocol()
        try:
            from OpenSSL.crypto import Error as OpenSSLError
        except ImportError:
            raise unittest.SkipTest("pyOpenSSL not available")
        tls_err = OpenSSLError([("x509 certificate routines", "", "certificate verify failed")])
        # set up a connected waiter
        loop = asyncio.new_event_loop()
        waiter = loop.create_future()
        protocol._connected_waiter = waiter
        with patch.object(type(protocol).__mro__[1], "datagram_received", side_effect=tls_err):
            protocol.datagram_received(b"\x00" * 10, ("127.0.0.1", 10000))
        # waiter should have the exception set
        self.assertTrue(waiter.done())
        self.assertIs(waiter.exception(), tls_err)
        self.assertIsNone(protocol._connected_waiter)
        loop.close()

    def test_no_error_on_normal_datagram(self):
        """Normal datagrams don't set _tls_error."""
        protocol = self._make_protocol()
        with patch.object(type(protocol).__mro__[1], "datagram_received"):
            protocol.datagram_received(b"\x00" * 10, ("127.0.0.1", 10000))
        self.assertIsNone(protocol._tls_error)


if __name__ == "__main__":
    unittest.main()
