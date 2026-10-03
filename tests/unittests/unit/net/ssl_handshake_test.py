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
import unittest
import subprocess
from threading import Thread
from unittest.mock import patch
from time import monotonic

from xpra.net.socket_util import (
    ssl_handshake, ssl_retry, get_server_certificate, SSLVerifyFailure, SSL_VERIFY_SELF_SIGNED,
)
from xpra.scripts.config import InitException, InitExit
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


OPENSSL = shutil.which("openssl")


class TestServerCertificateDownload(unittest.TestCase):

    def test_connection_failure_does_not_retry(self) -> None:
        display_desc = {"type": "ssl", "host": "127.0.0.1", "port": 10000, "timeout": 20}
        with patch("xpra.net.socket_util.socket_connect", return_value=None) as connect:
            with patch("xpra.scripts.main.time.sleep", side_effect=AssertionError("must not retry")):
                self.assertEqual(get_server_certificate(display_desc, "localhost"), "")
        connect.assert_called_once_with("127.0.0.1", 10000, timeout=20)
        self.assertNotIn("retry", display_desc)

    def test_resolution_failure(self) -> None:
        display_desc = {"type": "ssl", "host": "unreachable.invalid", "port": 10000}
        # In 5.1, socket_connect raises InitException when getaddrinfo fails:
        with patch("xpra.net.socket_util.socket_connect", side_effect=InitException("cannot get address")):
            self.assertEqual(get_server_certificate(display_desc, "localhost"), "")

    def test_handshake_timeout(self) -> None:
        sock, peer = socket.socketpair()
        self.addCleanup(sock.close)
        self.addCleanup(peer.close)
        display_desc = {"type": "ssl", "host": "127.0.0.1", "port": 10000}
        # A peer that never answers must not hang the certificate download:
        with patch("xpra.net.socket_util.retry_socket_connect", return_value=sock):
            with patch("xpra.net.socket_util.SSL_HANDSHAKE_TIMEOUT", 0.1):
                start = monotonic()
                self.assertEqual(get_server_certificate(display_desc, "localhost"), "")
                self.assertLess(monotonic() - start, 5)
        self.assertEqual(sock.fileno(), -1)


@unittest.skipUnless(OPENSSL, "openssl is required to generate a test certificate")
class SSLServerTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp(prefix="xpra-ssl-verify-")
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
            raise unittest.SkipTest(f"failed to generate a test certificate: {r.stderr.decode('utf8', 'replace')}")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self) -> None:
        # don't touch the user's ssl host config, and accept the certificate without a dialog:
        hosts_dir = os.path.join(tempfile.mkdtemp(prefix="xpra-ssl-hosts-"), "ssl", "hosts")
        self.addCleanup(shutil.rmtree, os.path.dirname(os.path.dirname(hosts_dir)), True)
        env = patch.dict(os.environ, {"XPRA_SSL_HOSTS_CONFIG_DIRS": hosts_dir})
        env.start()
        self.addCleanup(env.stop)
        self.confirm = patch("xpra.scripts.pinentry_wrapper.confirm", return_value=True)
        self.confirm.start()
        self.addCleanup(self.confirm.stop)
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(self.listener.close)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.listener.settimeout(10)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.cert, self.key)
        self.server_names = []
        server_context.set_servername_callback(lambda conn, name, context: self.server_names.append(name))

        def serve() -> None:
            while True:
                try:
                    conn, _ = self.listener.accept()
                except OSError:
                    return
                try:
                    with server_context.wrap_socket(conn, server_side=True) as ssl_conn:
                        ssl_conn.recv(1)
                except (OSError, ssl.SSLError):
                    pass
                finally:
                    conn.close()
        Thread(target=serve, daemon=True).start()
        self.port = self.listener.getsockname()[1]
        self.display_desc = {
            "type": "ssl",
            "host": "127.0.0.1",
            "port": self.port,
            "ssl-options": {"server-hostname": "localhost", "ca-certs": "default"},
        }


class TestServerCertificate(SSLServerTestCase):

    def check_certificate(self, display_desc: dict) -> None:
        with patch("ssl.get_server_certificate", side_effect=AssertionError("must not bypass the connection path")):
            cert_data = get_server_certificate(display_desc, "localhost")
        with open(self.cert, encoding="latin1") as f:
            self.assertEqual(ssl.PEM_cert_to_DER_cert(cert_data), ssl.PEM_cert_to_DER_cert(f.read()))
        self.assertEqual(self.server_names, ["localhost"])

    def test_download(self) -> None:
        self.check_certificate(self.display_desc)

    def test_download_via_proxy(self) -> None:
        display_desc = dict(self.display_desc, host="unreachable.invalid", **{"proxy-host": "127.0.0.1"})

        def proxy_connect(options: dict) -> socket.socket:
            self.assertEqual((options["host"], options["port"]), ("unreachable.invalid", self.port))
            return socket.create_connection(("127.0.0.1", self.port), timeout=5)
        with patch("xpra.net.socket_util.proxy_connect", side_effect=proxy_connect) as pc:
            self.check_certificate(display_desc)
        pc.assert_called_once()


# Python 3.6 has no `SSLCertVerificationError`, so verification failures can't be identified:
@unittest.skipUnless(hasattr(ssl, "SSLCertVerificationError"), "Python 3.7 or later is required")
class TestSSLVerifyFailure(SSLServerTestCase):

    def handshake(self, ca_certs: str = "") -> None:
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if ca_certs:
            context.load_verify_locations(cafile=ca_certs)
        else:
            context.load_default_certs()
        sock.setblocking(True)
        ssl_sock = context.wrap_socket(sock, server_hostname="localhost", do_handshake_on_connect=False)
        # `connect_to` closes the socket when the connection setup fails:
        with ssl_sock:
            ssl_handshake(ssl_sock, 5)

    def verify_failure(self) -> SSLVerifyFailure:
        with self.assertRaises(SSLVerifyFailure) as cm:
            self.handshake()
        e = cm.exception
        self.assertEqual(e.status, ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE)
        self.assertEqual(e.verify_code, SSL_VERIFY_SELF_SIGNED)
        return e

    def der(self, pem: str) -> bytes:
        return ssl.PEM_cert_to_DER_cert(pem)

    def test_retry_after_close(self) -> None:
        e = self.verify_failure()
        with open(self.cert, encoding="latin1") as f:
            server_cert = f.read()
        if hasattr(ssl.SSLSocket, "get_unverified_chain"):
            # the certificate that failed is recorded, no need to download it again:
            self.assertEqual(self.der(e.cert_data), self.der(server_cert))
        mods = ssl_retry(e, self.display_desc)
        self.assertEqual(list(mods.keys()), ["ca-certs"])
        with open(mods["ca-certs"], encoding="latin1") as f:
            self.assertEqual(self.der(f.read()), self.der(server_cert))
        # the accepted certificate is enough to connect:
        self.handshake(mods["ca-certs"])

    def check_download(self, display_desc: dict) -> None:
        e = self.verify_failure()
        # what older Python versions give us, which have no `get_unverified_chain()`:
        e.cert_data = ""
        with patch("ssl.get_server_certificate", side_effect=AssertionError("must not bypass the connection path")):
            mods = ssl_retry(e, display_desc)
        self.assertEqual(self.server_names, ["localhost", "localhost"])
        with open(self.cert, encoding="latin1") as f:
            server_cert = f.read()
        with open(mods["ca-certs"], encoding="latin1") as f:
            self.assertEqual(self.der(f.read()), self.der(server_cert))

    def test_retry_download(self) -> None:
        self.check_download(self.display_desc)

    def test_retry_download_via_proxy(self) -> None:
        # the destination is only reachable through the proxy:
        display_desc = dict(self.display_desc, host="unreachable.invalid", **{"proxy-host": "127.0.0.1"})
        port = self.port

        def proxy_connect(options: dict) -> socket.socket:
            self.assertEqual((options["host"], options["port"]), ("unreachable.invalid", port))
            return socket.create_connection(("127.0.0.1", port), timeout=5)
        with patch("xpra.net.socket_util.proxy_connect", side_effect=proxy_connect) as pc:
            self.check_download(display_desc)
        pc.assert_called_once()

    def test_retry_only_with_new_options(self) -> None:
        from xpra.scripts.main import apply_ssl_retry
        e = self.verify_failure()
        self.assertTrue(apply_ssl_retry(e, self.display_desc))
        self.assertNotEqual(self.display_desc["ssl-options"]["ca-certs"], "default")
        # failing again with the certificate we accepted must not retry forever:
        self.assertFalse(apply_ssl_retry(e, self.display_desc))
        # and errors other than certificate verification failures are not retried:
        self.assertFalse(apply_ssl_retry(InitExit(ExitCode.SSL_FAILURE, "test"), self.display_desc))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
