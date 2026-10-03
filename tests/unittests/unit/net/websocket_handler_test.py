#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
import socket
import unittest
from threading import Thread
from time import monotonic, sleep
from unittest.mock import patch

from xpra.net.websockets import handler
from unit.test_util import silence_error

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
    """ the upgrade request, with some header values replaced """
    lines = []
    for line in UPGRADE_REQUEST:
        header = line.split(b":")[0]
        name = header.decode().replace("-", "_").lower()
        if name in replace:
            line = b"%s: %s" % (header, replace[name])
        lines.append(line)
    return b"\r\n".join(lines + [b"", b""])


def status(response : bytes):
    return [line for line in response.split(b"\r\n") if line.startswith(b"HTTP/")]


class ServerSocket:
    """ runs the real request handler on one end of a socket pair """

    def __init__(self, new_websocket_client=None, timeout:float=5.0):
        self.client, self.server = socket.socketpair()
        self.server.settimeout(timeout)
        self.client.settimeout(5)
        self.upgraded = []
        self.new_websocket_client = new_websocket_client or self.upgraded.append
        self.thread = Thread(target=self.handle, daemon=True)
        self.thread.start()

    def handle(self) -> None:
        handler.WebSocketRequestHandler(self.server, ("peer", 0), self.new_websocket_client)

    def request(self, data : bytes) -> bytes:
        self.client.sendall(data)
        self.thread.join(5)
        self.client.settimeout(0.5)
        response = b""
        try:
            while True:
                data = self.client.recv(4096)
                if not data:
                    break
                response += data
        except OSError:
            pass
        return response

    def close(self) -> None:
        self.client.close()
        self.server.close()


class TestRequestReader(unittest.TestCase):

    def test_request_reader_sees_peeked_data(self):
        # the http request handler must see the data that was peeked before the upgrade,
        # ie: for tcp sockets upgraded to ssl, the decrypted data is consumed by the peek:
        from xpra.net.bytestreams import SocketPeekWrapper
        from xpra.net.http.http_handler import RequestReader
        client, server = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(server.close)
        server.settimeout(1)
        wrapper = SocketPeekWrapper(server, b"GET / HTTP/1.1\r\n\r\n")
        rfile = io.BufferedReader(RequestReader(wrapper, 10))
        self.assertEqual(rfile.readline(), b"GET / HTTP/1.1\r\n")
        self.assertEqual(rfile.readline(), b"\r\n")

    def test_request_timeout_not_logged_as_error(self):
        # before Python 3.10, `socket.timeout` is not a `TimeoutError`,
        # and that's what `BaseHTTPRequestHandler` passes to `log_error` when the deadline expires:
        from xpra.net.http import http_handler
        with patch.object(http_handler, "log") as log:
            http_handler.HTTPRequestHandler.log_error(None, "Request timed out: %r", socket.timeout("test"))
        log.error.assert_not_called()
        log.assert_called_once()


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

    def test_slow_request(self):
        # sending the request one byte at a time must not keep the handler forever,
        # even if each byte arrives well within the socket timeout:
        from xpra.net.http import http_handler
        with patch.object(http_handler, "REQUEST_TIMEOUT", 1):
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

    def test_protocol_list(self):
        for protocols in (b"binary, chat", b"chat, binary", b"chat,binary", b"chat , binary "):
            with self.subTest(protocols=protocols):
                server = self.server()
                response = server.request(upgrade_request(sec_websocket_protocol=protocols))
                self.assertEqual(status(response), [b"HTTP/1.1 101 Switching Protocols"])
                self.assertIn(b"Sec-WebSocket-Protocol: binary", response)

    def test_binary_protocol_required(self):
        from xpra.net.http import http_handler
        with patch.object(http_handler, "may_reload_headers", return_value={}) as reload_headers:
            server = self.server()
            with silence_error(handler):
                response = server.request(upgrade_request(sec_websocket_protocol=b"chat, base64"))
        self.assertTrue(status(response)[0].startswith(b"HTTP/1.0 403 "), response)
        reload_headers.assert_called_once_with(("/etc/xpra/http-headers",))
        self.assertEqual(server.upgraded, [])

    def test_failure_after_upgrade(self):
        #once the upgrade response is sent, the connection can only be closed:
        def new_websocket_client(_wsh):
            raise OSError("failed to start the protocol")
        server = self.server(new_websocket_client)
        with silence_error(handler):
            response = server.request(upgrade_request())
        self.assertEqual(status(response), [b"HTTP/1.1 101 Switching Protocols"])
        self.assertTrue(response.endswith(b"\r\n\r\n"))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
