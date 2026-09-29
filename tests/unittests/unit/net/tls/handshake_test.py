#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ssl
import socket
import unittest
from time import monotonic

from xpra.net.tls.socket import ssl_handshake
from xpra.scripts.config import InitExit


class TestSSLHandshakeTimeout(unittest.TestCase):

    def _check_silent_peer(self, server_side: bool) -> None:
        # the peer never sends anything, so the handshake can never complete:
        sock, peer = socket.socketpair()
        try:
            if server_side:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            else:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            # `do_wrap_socket` leaves the socket in blocking mode:
            sock.setblocking(True)
            ssl_sock = context.wrap_socket(sock, server_side=server_side, do_handshake_on_connect=False)
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


def main():
    unittest.main()


if __name__ == "__main__":
    main()
