#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import unittest
from threading import Thread
from time import monotonic, sleep
from unittest.mock import MagicMock, patch

UPGRADE_REQUEST = (
    b"GET / HTTP/1.1",
    b"Host: localhost",
    b"Upgrade: websocket",
    b"Connection: Upgrade",
    b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==",
    b"Sec-WebSocket-Version: 13",
    b"Sec-WebSocket-Protocol: binary",
)


def upgrade_request(**replace) -> bytes:
    """ the upgrade request, with some header values replaced (or removed with `None`) """
    lines = []
    for line in UPGRADE_REQUEST:
        name = line.split(b":")[0].decode().replace("-", "_").lower()
        if name in replace:
            if replace[name] is None:
                continue
            line = b"%s: %s" % (line.split(b":")[0], replace[name])
        lines.append(line)
    return b"\r\n".join(lines + [b"", b""])


class ServerSocket:
    """ runs the real request handler on one end of a socket pair """

    def __init__(self, new_websocket_client=None, timeout: float = 5.0):
        self.client, self.server = socket.socketpair()
        self.server.settimeout(timeout)
        self.client.settimeout(5)
        self.upgraded = []
        self.new_websocket_client = new_websocket_client or self.upgraded.append
        self.thread = Thread(target=self.handle, daemon=True)
        self.thread.start()

    def handle(self) -> None:
        from xpra.net.websockets.handler import WebSocketRequestHandler
        WebSocketRequestHandler(self.server, ("peer", 0), self.new_websocket_client)

    def request(self, data: bytes) -> bytes:
        self.client.sendall(data)
        self.thread.join(5)
        return self.read_response()

    def read_response(self) -> bytes:
        self.client.settimeout(0.5)
        response = b""
        try:
            while data := self.client.recv(4096):
                response += data
        except OSError:
            pass
        return response

    def close(self) -> None:
        self.client.close()
        self.server.close()


def status(response: bytes) -> list[bytes]:
    return [line for line in response.split(b"\r\n") if line.startswith(b"HTTP/")]


class TestWebSocketUpgrade(unittest.TestCase):

    def server(self, *args, **kwargs) -> ServerSocket:
        server = ServerSocket(*args, **kwargs)
        self.addCleanup(server.close)
        return server

    def test_upgrade(self):
        server = self.server()
        response = server.request(upgrade_request())
        self.assertEqual(status(response), [b"HTTP/1.1 101 Switching Protocols"])
        self.assertEqual(len(server.upgraded), 1)

    def test_protocol_list(self):
        for protocols in (b"binary, chat", b"chat, binary", b"chat,binary", b"chat , binary "):
            with self.subTest(protocols=protocols):
                server = self.server()
                response = server.request(upgrade_request(sec_websocket_protocol=protocols))
                self.assertEqual(status(response), [b"HTTP/1.1 101 Switching Protocols"])
                self.assertIn(b"Sec-WebSocket-Protocol: binary", response)

    def test_binary_protocol_required(self):
        server = self.server()
        response = server.request(upgrade_request(sec_websocket_protocol=b"chat, base64"))
        self.assertTrue(status(response)[0].startswith(b"HTTP/1.0 403 "))
        self.assertEqual(server.upgraded, [])

    def test_failure_after_upgrade(self):
        # once the upgrade response is sent, the connection can only be closed:
        def new_websocket_client(_wsh):
            raise OSError("failed to start the protocol")
        server = self.server(new_websocket_client)
        response = server.request(upgrade_request())
        self.assertEqual(status(response), [b"HTTP/1.1 101 Switching Protocols"])
        self.assertTrue(response.endswith(b"\r\n\r\n"))
        self.assertEqual(server.client.recv(1), b"")

    def test_unsupported_version(self):
        server = self.server()
        response = server.request(upgrade_request(sec_websocket_version=b"99"))
        self.assertTrue(status(response)[0].startswith(b"HTTP/1.0 426 "))
        self.assertIn(b"Sec-WebSocket-Version: 13, 8, 7\r\n", response)
        self.assertEqual(server.upgraded, [])

    def test_slow_request(self):
        # sending the request one byte at a time must not keep the handler forever,
        # even if each byte arrives well within the socket timeout:
        from xpra.net.http import handler
        with patch.object(handler, "REQUEST_TIMEOUT", 1):
            server = self.server(timeout=5)
            start = monotonic()
            try:
                for c in upgrade_request():
                    server.client.send(bytes([c]))
                    sleep(0.2)
                    if not server.thread.is_alive():
                        break
            except OSError:
                pass
            server.thread.join(5)
        self.assertFalse(server.thread.is_alive())
        self.assertLess(monotonic() - start, 3)
        self.assertEqual(server.upgraded, [])

    def test_request_timeout_is_not_the_socket_timeout(self):
        # the deadline only applies to the request, not to the websocket connection:
        timeouts = []
        server = self.server(lambda wsh: timeouts.append(wsh.connection.gettimeout()), timeout=5)
        server.request(upgrade_request())
        self.assertEqual(timeouts, [5])


class TestWebSocketHandler(unittest.TestCase):

    def _make_handler(self, headers=None, path="/", redirect_https=False, origin="auto"):
        """Build a WebSocketRequestHandler with mocked I/O."""
        from xpra.net.websockets.handler import WebSocketRequestHandler

        handler = WebSocketRequestHandler.__new__(WebSocketRequestHandler)
        handler.headers = headers or {}
        handler.path = path
        handler.redirect_https = redirect_https
        handler.origin = origin
        handler.only_upgrade = False
        handler.close_connection = False
        handler.new_websocket_client = MagicMock()
        handler.connection = MagicMock()
        handler.wfile = MagicMock()
        handler.request = MagicMock()
        return handler

    # handle_websocket – header validation
    def test_handle_websocket_missing_version(self):
        handler = self._make_handler(headers={})
        with self.assertRaises(ValueError) as ctx:
            handler.handle_websocket()
        assert "Version" in str(ctx.exception)

    def test_handle_websocket_unsupported_version(self):
        handler = self._make_handler(headers={"Sec-WebSocket-Version": "99"})
        with self.assertRaises(ValueError) as ctx:
            handler.handle_websocket()
        assert "Unsupported" in str(ctx.exception) or "protocol" in str(ctx.exception).lower()

    def test_handle_websocket_missing_binary_protocol(self):
        handler = self._make_handler(headers={
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Protocol": "base64",
        })
        with self.assertRaises(ValueError) as ctx:
            handler.handle_websocket()
        assert "binary" in str(ctx.exception).lower()

    def test_handle_websocket_missing_key(self):
        handler = self._make_handler(headers={
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Protocol": "binary",
            "Sec-WebSocket-Key": "",
        })
        with self.assertRaises(ValueError) as ctx:
            handler.handle_websocket()
        assert "Key" in str(ctx.exception)

    # handle_websocket - origin validation
    def _upgrade_headers(self, **extra) -> dict:
        headers = {
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Protocol": "binary",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        }
        headers.update(extra)
        return headers

    def test_handle_websocket_cross_origin(self):
        handler = self._make_handler(headers=self._upgrade_headers(
            Host="localhost:14500",
            Origin="http://evil.example",
        ))
        with self.assertRaises(ValueError) as ctx:
            handler.handle_websocket()
        assert "origin" in str(ctx.exception).lower()
        assert not handler.new_websocket_client.called
        # the origin must not be echoed back to the client:
        assert "evil.example" not in str(ctx.exception)

    def test_handle_websocket_cross_origin_allowed(self):
        handler = self._make_handler(headers=self._upgrade_headers(
            Host="localhost:14500",
            Origin="https://desktop.example",
        ), origin="https://desktop.example")
        handler.write_byte_strings = lambda *bs: None
        handler.finish = lambda: None
        handler.handle_websocket()
        assert handler.new_websocket_client.called

    def test_handle_websocket_valid(self):
        written = []
        handler = self._make_handler(headers=self._upgrade_headers(
            Host="localhost:14500",
            Origin="http://localhost:14500",
        ))
        handler.write_byte_strings = lambda *bs: written.append(b"\r\n".join(bs))

        def fake_finish():
            pass
        handler.finish = fake_finish

        from unittest.mock import patch as mock_patch
        # super().finish() must not crash
        with mock_patch.object(type(handler).__mro__[2], "finish", lambda self: None, create=True):
            handler.handle_websocket()
        assert handler.new_websocket_client.called
        assert written

    # do_redirect_https
    def test_redirect_https_empty_host_header(self):
        # HTTPMessage returns None/empty for absent Host; simulate with empty string
        handler = self._make_handler(headers={"Host": ""}, redirect_https=True)
        errors = []
        handler.send_error = lambda code, msg="": errors.append((code, msg))
        handler.do_redirect_https()
        assert errors, "should have called send_error"
        assert errors[0][0] == 400

    def test_redirect_https_invalid_hostname(self):
        handler = self._make_handler(headers={"Host": "not a valid host!"}, redirect_https=True)
        errors = []
        handler.send_error = lambda code, msg="": errors.append((code, msg))
        handler.do_redirect_https()
        assert any(e[0] == 400 for e in errors)

    def test_redirect_https_valid_host_permanent(self):
        from xpra.net.websockets.handler import HTTPS_REDIRECT_PERMANENT
        written = []
        handler = self._make_handler(headers={"Host": "example.com"}, path="/index.html", redirect_https=True)
        handler.write_byte_strings = lambda *bs: written.extend(bs)
        handler.do_redirect_https()
        combined = b" ".join(written)
        assert b"https" in combined
        if HTTPS_REDIRECT_PERMANENT:
            assert b"301" in combined
        else:
            assert b"307" in combined

    def test_redirect_https_host_with_port(self):
        written = []
        handler = self._make_handler(headers={"Host": "example.com:8080"}, path="/", redirect_https=True)
        handler.write_byte_strings = lambda *bs: written.extend(bs)
        handler.do_redirect_https()
        combined = b" ".join(written)
        assert b"https" in combined
        assert b"example.com" in combined

    # write_byte_strings
    def test_write_byte_strings(self):
        handler = self._make_handler()
        written = []
        handler.wfile.write = lambda data: written.append(data)
        handler.wfile.flush = lambda: None
        handler.write_byte_strings(b"HTTP/1.1 200 OK", b"Content-Type: text/plain", b"", b"body")
        assert len(written) == 1
        assert b"\r\n" in written[0]
        assert b"HTTP/1.1 200 OK" in written[0]

    # module-level constants
    def test_constants(self):
        from xpra.net.websockets.handler import SUPPORT_HyBi_PROTOCOLS, WEBSOCKET_ONLY_UPGRADE
        assert "13" in SUPPORT_HyBi_PROTOCOLS
        assert "7" in SUPPORT_HyBi_PROTOCOLS
        assert "8" in SUPPORT_HyBi_PROTOCOLS
        assert isinstance(WEBSOCKET_ONLY_UPGRADE, bool)

    def test_server_version(self):
        from xpra.net.websockets.handler import WebSocketRequestHandler
        assert "WebSocket" in WebSocketRequestHandler.server_version


def main():
    unittest.main()


if __name__ == '__main__':
    main()
