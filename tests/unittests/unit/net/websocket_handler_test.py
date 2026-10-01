#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import unittest
from threading import Thread

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

    def __init__(self, new_websocket_client=None):
        self.client, self.server = socket.socketpair()
        self.server.settimeout(5)
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


class TestWebSocketUpgrade(unittest.TestCase):

    def server(self, *args) -> ServerSocket:
        server = ServerSocket(*args)
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
        with silence_error(handler):
            response = server.request(upgrade_request(sec_websocket_protocol=b"chat, base64"))
        self.assertTrue(status(response)[0].startswith(b"HTTP/1.0 403 "))
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
