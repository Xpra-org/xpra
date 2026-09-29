#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
    Drive the real server connection handling code with real sockets and real TLS:
    `accept_connection` then `ServerCore.handle_new_connection`,
    both for `ssl` sockets and for `tcp` sockets upgraded to `ssl`.
"""

import os
import ssl
import shutil
import socket
import tempfile
import subprocess
import unittest
from functools import partial
from threading import Thread
from unittest.mock import patch

from xpra.net.socket_util import SocketListener, accept_connection
from xpra.net.tls import socket as tls_socket
from xpra.net.bytestreams import SSLSocketConnection
from xpra.server.core import ServerCore

OPENSSL = shutil.which("openssl")
# don't wait 20 seconds for clients that never complete the handshake:
HANDSHAKE_TIMEOUT = 1


def make_client_hello() -> bytes:
    # a real `ClientHello`, without completing the handshake:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    ssl_obj = context.wrap_bio(incoming, outgoing)
    try:
        ssl_obj.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return outgoing.read()


@unittest.skipUnless(OPENSSL, "openssl is required to generate a test certificate")
class ServerSSLConnectionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp(prefix="xpra-ssl-connection-")
        cls.cert = os.path.join(cls.tmpdir, "cert.pem")
        cls.key = os.path.join(cls.tmpdir, "key.pem")
        cmd = [
            OPENSSL, "req", "-new", "-x509", "-days", "1", "-nodes",
            "-newkey", "rsa:2048", "-keyout", cls.key, "-out", cls.cert,
            "-subj", "/CN=localhost",
        ]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if r.returncode != 0 or not os.path.exists(cls.cert):
            shutil.rmtree(cls.tmpdir, ignore_errors=True)
            raise unittest.SkipTest("failed to generate a test certificate: %s" % r.stderr.decode("utf8", "replace"))

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self) -> None:
        server = ServerCore.__new__(ServerCore)
        server._socket_timeout = 5
        server._ssl_attributes = {
            "cert": self.cert,
            "key": self.key,
            "client-verify-mode": "none",
        }
        # only xpra over ssl, no http:
        server.ssl_mode = "tcp"
        server.ssl_upgrade = True
        server.websocket_upgrade = False
        server.rdp_upgrade = False
        server._rfb_upgrade = 0
        server.subsystems = {}
        self.protocols = []
        server.make_protocol = lambda socktype, conn, *_args, **_kwargs: self.protocols.append((socktype, conn))
        self.server = server
        # keep track of all the server side ssl sockets:
        self.ssl_sockets = []
        do_wrap_socket = tls_socket.do_wrap_socket

        def record_wrap_socket(*args, **kwargs):
            ssl_sock = do_wrap_socket(*args, **kwargs)
            self.ssl_sockets.append(ssl_sock)
            return ssl_sock
        handshake = partial(tls_socket.ssl_handshake, timeout=HANDSHAKE_TIMEOUT)
        for patcher in (
            patch.object(tls_socket, "do_wrap_socket", record_wrap_socket),
            patch.object(tls_socket, "ssl_handshake", handshake),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.clients = []
        self.conns = []

    def tearDown(self) -> None:
        for sock in self.clients:
            sock.close()
        for conn in self.conns:
            conn.close()
        for ssl_sock in self.ssl_sockets:
            ssl_sock.close()

    def listen(self, socktype: str) -> SocketListener:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return SocketListener(socktype, sock, sock.getsockname(), {}, lambda: None, sock.close)

    def connect(self, listener: SocketListener) -> socket.socket:
        client = socket.create_connection(listener.address, timeout=10)
        self.clients.append(client)
        return client

    def handle(self, listener: SocketListener) -> None:
        conn = accept_connection(listener, self.server._socket_timeout)
        self.assertIsNotNone(conn)
        self.server.handle_new_connection(listener, conn)

    def check_connection(self, socktype: str) -> None:
        listener = self.listen(socktype)
        client = self.connect(listener)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        ssl_client = context.wrap_socket(client, do_handshake_on_connect=False)
        self.clients.append(ssl_client)
        # the client handshake must run concurrently with the server's:
        client_thread = Thread(target=ssl_client.do_handshake, daemon=True)
        client_thread.start()
        self.handle(listener)
        client_thread.join(10)
        self.assertEqual(len(self.protocols), 1, "the connection was not handed over to a protocol")
        proto_socktype, conn = self.protocols[0]
        self.conns.append(conn)
        # upgraded connections keep the socktype of the listener:
        self.assertEqual(proto_socktype, socktype)
        self.assertEqual(conn.socktype, "ssl")
        # the read and write threads need the ssl calls to be serialized, see #4918:
        self.assertIsInstance(conn, SSLSocketConnection)
        self.assertIs(conn._socket, self.ssl_sockets[0])
        # and data can flow both ways over the encrypted connection:
        ssl_client.sendall(b"hello")
        self.assertEqual(conn.read(1024), b"hello")
        conn.write(b"world")
        self.assertEqual(ssl_client.recv(1024), b"world")

    def test_ssl_socket(self) -> None:
        self.check_connection("ssl")

    def test_tcp_upgraded_to_ssl(self) -> None:
        self.check_connection("tcp")

    def assert_closed(self) -> None:
        self.assertEqual(self.protocols, [], "the connection should not have been handed over to a protocol")
        self.assertEqual(len(self.ssl_sockets), 1, "the connection should have been wrapped with ssl")
        # the server must not leave the connection open:
        self.assertEqual(self.ssl_sockets[0].fileno(), -1, "the server did not close the ssl socket")

    def check_closed_during_handshake(self, socktype: str) -> None:
        listener = self.listen(socktype)
        client = self.connect(listener)
        client.sendall(make_client_hello())
        client.close()
        self.handle(listener)
        self.assert_closed()

    def test_ssl_socket_closed_during_handshake(self) -> None:
        self.check_closed_during_handshake("ssl")

    def test_tcp_upgrade_closed_during_handshake(self) -> None:
        self.check_closed_during_handshake("tcp")

    def check_incomplete_handshake(self, socktype: str) -> None:
        listener = self.listen(socktype)
        client = self.connect(listener)
        # start the handshake but never complete it:
        client.sendall(make_client_hello())
        self.handle(listener)
        self.assert_closed()
        # and the client can see that the server has closed the connection:
        client.settimeout(5)
        while data := client.recv(65536):
            self.assertTrue(data)

    def test_ssl_socket_incomplete_handshake(self) -> None:
        self.check_incomplete_handshake("ssl")

    def test_tcp_upgrade_incomplete_handshake(self) -> None:
        self.check_incomplete_handshake("tcp")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
