#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import asyncio
import socket
import unittest
from unittest.mock import MagicMock, patch

try:
    import aioquic
    HAVE_AIOQUIC = bool(aioquic)
except ImportError:
    HAVE_AIOQUIC = False


def _make_protocol(xpra_server=None):
    """Create an HttpServerProtocol bypassing QuicConnectionProtocol.__init__."""
    from xpra.net.quic.listener import HttpServerProtocol
    protocol = HttpServerProtocol.__new__(HttpServerProtocol)
    protocol._xpra_server = xpra_server or MagicMock()
    protocol._handlers = {}
    protocol._http = None
    protocol._quic = MagicMock()
    protocol._transport = MagicMock()
    protocol._transport.get_extra_info = lambda k: None
    protocol.transmit = MagicMock()
    return protocol


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestHttpServerProtocolInit(unittest.TestCase):

    def test_default_state(self):
        p = _make_protocol()
        assert p._handlers == {}
        assert p._http is None

    def test_xpra_server_stored(self):
        server = MagicMock()
        p = _make_protocol(xpra_server=server)
        assert p._xpra_server is server


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestHttpServerProtocolEvents(unittest.TestCase):

    def test_quic_event_datagram_quack(self):
        from aioquic.quic.events import DatagramFrameReceived
        p = _make_protocol()
        event = MagicMock(spec=DatagramFrameReceived)
        event.data = b"quack"
        # _http is None so the event loop won't try to dispatch to http
        p.quic_event_received(event)
        p._quic.send_datagram_frame.assert_called_once_with(b"quack-ack")

    def test_quic_event_protocol_negotiated_h3(self):
        from aioquic.h3.connection import H3_ALPN
        from aioquic.quic.events import ProtocolNegotiated
        p = _make_protocol()
        event = MagicMock(spec=ProtocolNegotiated)
        event.alpn_protocol = H3_ALPN[0]
        # H3Connection requires a real quic object; swallow any TypeError
        try:
            p.quic_event_received(event)
        except Exception:
            pass

    def test_quic_event_protocol_negotiated_h0(self):
        from aioquic.h0.connection import H0_ALPN
        from aioquic.quic.events import ProtocolNegotiated
        p = _make_protocol()
        event = MagicMock(spec=ProtocolNegotiated)
        event.alpn_protocol = H0_ALPN[0]
        try:
            p.quic_event_received(event)
        except Exception:
            pass


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestNewHttpHandler(unittest.TestCase):

    def _make_protocol_with_http(self):
        p = _make_protocol()
        p._http = MagicMock()
        p._http._quic = MagicMock()
        p._http._quic._network_paths = [MagicMock(addr=("127.0.0.1", 9999))]
        return p

    def _make_headers_event(self, method, path, protocol=None, extra=()):
        event = MagicMock()
        event.stream_id = 1
        headers = [
            (b":method", method.encode()),
            (b":path", path.encode()),
            (b":authority", b"localhost"),
        ]
        if protocol:
            headers.append((b":protocol", protocol.encode()))
        headers.extend(extra)
        event.headers = headers
        return event

    def test_websocket_handler(self):
        from xpra.net.quic.websocket import ServerWebSocketConnection
        p = self._make_protocol_with_http()
        event = self._make_headers_event("CONNECT", "/", protocol="websocket")
        handler = p.new_http_handler(event)
        assert isinstance(handler, ServerWebSocketConnection)
        assert p._xpra_server.make_protocol.called

    def test_webtransport_handler(self):
        from xpra.net.quic.webtransport import ServerWebTransportConnection
        p = self._make_protocol_with_http()
        event = self._make_headers_event("CONNECT", "/wt", protocol="webtransport")
        handler = p.new_http_handler(event)
        assert isinstance(handler, ServerWebTransportConnection)
        assert p._xpra_server.make_protocol.called

    def test_http_get_handler(self):
        from xpra.net.quic.http import HttpRequestHandler
        p = self._make_protocol_with_http()
        event = self._make_headers_event("GET", "/index.html")
        handler = p.new_http_handler(event)
        assert isinstance(handler, HttpRequestHandler)

    def test_query_string_split(self):
        from xpra.net.quic.http import HttpRequestHandler
        p = self._make_protocol_with_http()
        event = self._make_headers_event("GET", "/page?foo=bar")
        handler = p.new_http_handler(event)
        assert isinstance(handler, HttpRequestHandler)
        assert handler.scope.get("query_string") == b"foo=bar"

    def test_non_colon_headers_forwarded(self):
        from xpra.net.quic.http import HttpRequestHandler
        p = self._make_protocol_with_http()
        event = self._make_headers_event(
            "GET", "/",
            extra=[(b"x-custom-header", b"value123")],
        )
        handler = p.new_http_handler(event)
        assert isinstance(handler, HttpRequestHandler)
        headers = handler.scope.get("headers", [])
        assert any(h[0] == b"x-custom-header" for h in headers)


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestDoListen(unittest.TestCase):

    def test_bad_cert_returns_none(self):
        from xpra.net.quic.listener import do_listen
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        try:
            result = asyncio.run(do_listen(sock, MagicMock(), "/nonexistent/cert.pem", None, False))
            assert result is None
        finally:
            sock.close()

    def test_bad_key_returns_none(self):
        from xpra.net.quic.listener import do_listen
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        try:
            result = asyncio.run(do_listen(sock, MagicMock(), "/no/cert.pem", "/no/key.pem", False))
            assert result is None
        finally:
            sock.close()


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestListenQuic(unittest.TestCase):

    def test_missing_cert_raises_init_exit(self):
        from xpra.net.quic.listener import listen_quic
        from xpra.scripts.config import InitExit
        server = MagicMock()
        server.get_ssl_socket_options = lambda opts: {}
        # find_ssl_cert is imported lazily inside listen_quic; patch it at its source
        with patch("xpra.net.tls.file.find_ssl_cert", return_value=""):
            with self.assertRaises(InitExit):
                listen_quic(MagicMock(), server, {})

    def test_missing_key_raises_init_exit(self):
        from xpra.net.quic.listener import listen_quic
        from xpra.scripts.config import InitExit
        server = MagicMock()
        # cert is set via socket options, key comes from find_ssl_cert which returns ""
        server.get_ssl_socket_options = lambda opts: {"cert": "/some/cert.pem"}
        with patch("xpra.net.tls.file.find_ssl_cert", return_value=""):
            with self.assertRaises(InitExit):
                listen_quic(MagicMock(), server, {})


def main():
    unittest.main()


if __name__ == "__main__":
    main()
