#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import ssl
import shutil
import socket
import tempfile
import threading
import subprocess
import unittest
from time import monotonic
from unittest.mock import patch

from xpra.net.common import ConnectionClosedException
from xpra.net.connect import connect_to_tcp
from xpra.net.websockets import common
from xpra.scripts.config import InitExit

OPENSSL = shutil.which("openssl")

# the upgrade deadline is MAX_WRITE_TIME + MAX_READ_TIME:
MAX_TIME = 0.5
# how long a failing connection attempt may take, generously:
FAIL_TIME = 5
# give up waiting for a connection attempt that is stuck:
HANG_TIME = 10
# the server keeps the connection open for these, so it can tell when the client closes it:
WAITING_BEHAVIOURS = ("silent", "partial", "not-found", "auth", "no-tls")


class FakeServer:
    """
        Accepts a single connection and responds to the websocket upgrade request
        using the given `behaviour`.
    """

    def __init__(self, behaviour: str, ssl_context=None):
        self.behaviour = behaviour
        self.ssl_context = ssl_context
        self.stop = threading.Event()
        self.client_closed = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.sock = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        for s in (self.sock, self.listener):
            if s:
                try:
                    s.close()
                except OSError:
                    pass
        self.thread.join(5)

    def wait(self) -> None:
        # keep the connection open without sending anything, until the client closes it:
        self.sock.settimeout(0.1)
        while not self.stop.is_set():
            try:
                if not self.sock.recv(4096):
                    break
            except TimeoutError:
                continue
            except (OSError, ValueError):
                break
        if not self.stop.is_set():
            self.client_closed.set()

    def run(self) -> None:
        try:
            self.sock, _ = self.listener.accept()
            if self.behaviour == "no-tls":
                self.wait()
                return
            if self.ssl_context:
                self.sock = self.ssl_context.wrap_socket(self.sock, server_side=True)
            request = self.sock.recv(4096)
            getattr(self, "do_" + self.behaviour.replace("-", "_"))(request)
        except OSError:
            if not self.stop.is_set():
                raise

    def do_upgrade(self, request: bytes) -> None:
        key = b""
        for line in request.split(b"\r\n"):
            if line.lower().startswith(b"sec-websocket-key:"):
                key = line.split(b":", 1)[1].strip()
        accept = common.make_websocket_accept_hash(key)
        self.sock.sendall(b"\r\n".join((
            b"HTTP/1.1 101 Switching Protocols",
            b"Upgrade: websocket",
            b"Connection: Upgrade",
            b"Sec-WebSocket-Protocol: binary",
            b"Sec-WebSocket-Accept: " + accept,
            b"", b"",
        )))
        self.wait()

    def do_silent(self, _request: bytes) -> None:
        self.wait()

    def do_partial(self, _request: bytes) -> None:
        self.sock.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n")
        self.wait()

    def do_not_found(self, _request: bytes) -> None:
        self.sock.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
        self.wait()

    def do_bad_gateway(self, _request: bytes) -> None:
        self.sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        self.sock.close()

    def do_close(self, _request: bytes) -> None:
        self.sock.close()

    def do_auth(self, _request: bytes) -> None:
        self.sock.sendall(b"HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Basic realm=\"xpra\"\r\n\r\n")
        self.wait()


class WebsocketUpgradeTest(unittest.TestCase):

    dtype = "ws"

    def setUp(self) -> None:
        self.servers: list[FakeServer] = []
        self.conns = []
        # use short upgrade time limits to keep the tests fast:
        self.patches = [
            patch.object(common, "MAX_READ_TIME", MAX_TIME),
            patch.object(common, "MAX_WRITE_TIME", MAX_TIME),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        for conn in self.conns:
            conn.close()
        for server in self.servers:
            server.close()

    def get_server_ssl_context(self):
        return None

    def get_ssl_options(self) -> dict:
        return {}

    def connect(self, behaviour: str, timeout=20):
        server = FakeServer(behaviour, self.get_server_ssl_context())
        self.servers.append(server)
        display_desc = {
            "type": self.dtype,
            "display_name": f"{self.dtype}://127.0.0.1:{server.port}/",
            "host": "127.0.0.1",
            "port": server.port,
            "display": "",
            "retry": False,
            "timeout": timeout,
            "ssl-options": self.get_ssl_options(),
        }
        # connect from a thread, so a regression fails the test instead of hanging it:
        result = {}

        def attempt() -> None:
            try:
                result["conn"] = connect_to_tcp(display_desc)
            except Exception as e:
                result["error"] = e

        thread = threading.Thread(target=attempt, daemon=True)
        thread.start()
        thread.join(HANG_TIME)
        if thread.is_alive():
            self.fail(f"connecting to a {behaviour!r} server is still blocked after {HANG_TIME} seconds")
        if "error" in result:
            raise result["error"]
        conn = result["conn"]
        self.conns.append(conn)
        return conn

    def check_fails(self, behaviour: str, exception_type, message: str, timeout=20, max_time=FAIL_TIME) -> None:
        start = monotonic()
        with self.assertRaises(exception_type) as cm:
            self.connect(behaviour, timeout)
        elapsed = monotonic() - start
        self.assertIn(message, str(cm.exception))
        self.assertLess(elapsed, max_time, f"{behaviour!r} took {elapsed:.1f} seconds")
        if behaviour in WAITING_BEHAVIOURS:
            # the client must not leak its socket when the connection fails:
            server = self.servers[-1]
            self.assertTrue(server.client_closed.wait(2), f"the client did not close its socket after {behaviour!r}")

    def test_upgrade(self) -> None:
        conn = self.connect("upgrade")
        self.assertTrue(conn)
        self.assertEqual(conn.deadline, 0, "the upgrade deadline should have been cleared")

    def test_silent(self) -> None:
        # the server accepts the connection but never responds:
        self.check_fails("silent", TimeoutError, "no websocket upgrade response")

    def test_partial(self) -> None:
        # the server sends some headers, then stalls:
        self.check_fails("partial", TimeoutError, "incomplete websocket upgrade response")

    def test_not_found(self) -> None:
        # a complete response which is not an upgrade, and the connection is kept open:
        self.check_fails("not-found", ValueError, "HTTP/1.1 404 Not Found", max_time=MAX_TIME)

    def test_bad_gateway(self) -> None:
        # ie: a proxy whose backend is not available:
        self.check_fails("bad-gateway", ValueError, "HTTP/1.1 502 Bad Gateway", max_time=MAX_TIME)

    def test_close(self) -> None:
        # the server closes the connection without responding,
        # this must fail straight away rather than spinning until the time limit:
        self.check_fails("close", ConnectionClosedException, "closed the connection", max_time=MAX_TIME)

    def test_auth(self) -> None:
        self.check_fails("auth", ValueError, "requires authentication", max_time=MAX_TIME)


@unittest.skipUnless(OPENSSL, "openssl is required to generate a test certificate")
class SecureWebsocketUpgradeTest(WebsocketUpgradeTest):

    dtype = "wss"

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp(prefix="xpra-wss-upgrade-")
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

    def get_server_ssl_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        return context

    def get_ssl_options(self) -> dict:
        return {
            "server-side": False,
            "server-verify-mode": "none",
            "check-hostname": False,
            "server-hostname": "localhost",
        }

    def test_no_tls(self) -> None:
        # the server accepts the connection but never starts the TLS handshake:
        self.check_fails("no-tls", InitExit, "SSL handshake timed out", timeout=1)

    # the other tests use the default connection timeout (20 seconds),
    # so `test_silent` and `test_partial` also verify that the SSL connection
    # does not wait past the upgrade deadline


def main():
    unittest.main()


if __name__ == "__main__":
    main()
