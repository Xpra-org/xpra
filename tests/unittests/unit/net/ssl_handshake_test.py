#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ssl
import socket
import unittest
from threading import Thread
from time import monotonic

from xpra.net.socket_util import ssl_handshake
from xpra.scripts.config import InitExit
from xpra.exit_codes import ExitCode


class TestSSLHandshakeTimeout(unittest.TestCase):

    @staticmethod
    def wrap(sock, server_side: bool):
        if server_side:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        else:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        # `do_wrap_socket` leaves the socket in blocking mode:
        sock.setblocking(True)
        return context.wrap_socket(sock, server_side=server_side, do_handshake_on_connect=False)

    def _check_silent_peer(self, server_side: bool) -> None:
        # the peer never sends anything, so the handshake can never complete:
        sock, peer = socket.socketpair()
        try:
            ssl_sock = self.wrap(sock, server_side)
            start = monotonic()
            with self.assertRaises(InitExit) as cm:
                ssl_handshake(ssl_sock, 0.5)
            elapsed = monotonic() - start
            self.assertIn("timed out", str(cm.exception))
            self.assertLess(elapsed, 5)
            # the original timeout (blocking) must be restored:
            self.assertIsNone(ssl_sock.gettimeout())
            ssl_sock.close()
        finally:
            sock.close()
            peer.close()

    def test_client_side_timeout(self) -> None:
        self._check_silent_peer(False)

    def test_server_side_timeout(self) -> None:
        self._check_silent_peer(True)

    def _check_closed_peer(self, server_side: bool, read_first: bool) -> None:
        # the peer closes the connection without completing the handshake:
        sock, peer = socket.socketpair()

        def close_peer() -> None:
            if read_first:
                peer.recv(4096)
            peer.close()
        closer = Thread(target=close_peer, daemon=True)
        try:
            ssl_sock = self.wrap(sock, server_side)
            closer.start()
            if not read_first:
                closer.join()
            with self.assertRaises(InitExit) as cm:
                ssl_handshake(ssl_sock, 5)
            self.assertEqual(cm.exception.status, ExitCode.SSL_FAILURE)
            self.assertIn("closed during the SSL handshake", str(cm.exception))
            ssl_sock.close()
        finally:
            closer.join(5)
            sock.close()

    def test_client_side_closed(self) -> None:
        # the server hangs up after receiving the `ClientHello`:
        self._check_closed_peer(False, True)

    def test_client_side_closed_before_hello(self) -> None:
        self._check_closed_peer(False, False)

    def test_server_side_closed(self) -> None:
        # ie: a port scanner or a health check
        self._check_closed_peer(True, False)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
