#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

from xpra.log import Logger

log = Logger("test")

XVNC = shutil.which("Xvnc") or shutil.which("Xtigervnc")
OPENSSL = shutil.which("openssl")

# how long to wait for Xvnc to start listening, and for the handshake to complete:
START_TIMEOUT = 20
CONNECT_TIMEOUT = 20


def free_display_no() -> int:
    used = set()
    xdir = "/tmp/.X11-unix"
    if os.path.isdir(xdir):
        for f in os.listdir(xdir):
            if f.startswith("X"):
                try:
                    used.add(int(f[1:]))
                except ValueError:
                    pass
    for n in range(101, 1000):
        if n not in used:
            return n
    raise RuntimeError("no free X11 display number found")


def free_tcp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class ImmediateScheduler:
    # the RFB protocol normally schedules onto the GLib main loop (not running in
    # this test); run idle callbacks inline and timeouts on a throwaway timer:
    def idle_add(self, fn, *args, **kwargs) -> int:
        fn(*args, **kwargs)
        return 0

    def timeout_add(self, timeout, fn, *args, **kwargs) -> int:
        t = threading.Timer(timeout / 1000.0, fn, args, kwargs)
        t.daemon = True
        t.start()
        return 0

    def source_remove(self, tid) -> None:
        pass


@unittest.skipUnless(XVNC and OPENSSL, "Xvnc and openssl are required for this test")
class TestRFBVeNCrypt(unittest.TestCase):
    """
    Spawn a real TigerVNC `Xvnc` server configured for VeNCrypt + X509 (TLS), then
    connect to it with xpra's `RFBClientProtocol` and verify that the VeNCrypt
    negotiation, the (real) TLS handshake and the RFB ServerInit all complete.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="xpra-rfb-vencrypt-")
        cls.cert = os.path.join(cls.tmpdir, "cert.pem")
        cls.key = os.path.join(cls.tmpdir, "key.pem")
        # a throwaway self-signed certificate for the server to present:
        cmd = [
            OPENSSL, "req", "-new", "-x509", "-days", "1", "-nodes",
            "-newkey", "rsa:2048", "-keyout", cls.key, "-out", cls.cert,
            "-subj", "/CN=localhost",
        ]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if r.returncode != 0 or not os.path.exists(cls.cert):
            shutil.rmtree(cls.tmpdir, ignore_errors=True)
            raise unittest.SkipTest("failed to generate a test certificate: %s" % r.stderr.decode("utf8", "replace"))

        cls.display = ":%i" % free_display_no()
        cls.port = free_tcp_port()
        env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
        env["HOME"] = cls.tmpdir
        cmd = [
            XVNC, cls.display,
            "-rfbport", str(cls.port),
            "-localhost",
            "-SecurityTypes", "X509None",
            "-X509Cert", cls.cert,
            "-X509Key", cls.key,
            "-geometry", "320x240", "-depth", "24",
            "-desktop", "xpra-rfb-test",
        ]
        cls.xvnc_log = open(os.path.join(cls.tmpdir, "xvnc.log"), "wb")
        log("starting Xvnc: %s", " ".join(cmd))
        cls.xvnc = subprocess.Popen(cmd, env=env, stdout=cls.xvnc_log, stderr=subprocess.STDOUT)
        # wait until the RFB port accepts connections:
        deadline = time.monotonic() + START_TIMEOUT
        ready = False
        while time.monotonic() < deadline:
            if cls.xvnc.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=1):
                    ready = True
                    break
            except OSError:
                time.sleep(0.25)
        if not ready:
            output = cls._read_xvnc_log()
            cls._stop_xvnc()
            shutil.rmtree(cls.tmpdir, ignore_errors=True)
            raise unittest.SkipTest("Xvnc did not start listening on port %i:\n%s" % (cls.port, output))

    @classmethod
    def _read_xvnc_log(cls) -> str:
        try:
            cls.xvnc_log.flush()
            with open(os.path.join(cls.tmpdir, "xvnc.log"), "rb") as f:
                return f.read().decode("utf8", "replace")
        except OSError:
            return ""

    @classmethod
    def _stop_xvnc(cls):
        xvnc = getattr(cls, "xvnc", None)
        if xvnc and xvnc.poll() is None:
            xvnc.terminate()
            try:
                xvnc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                xvnc.kill()
        if getattr(cls, "xvnc_log", None):
            try:
                cls.xvnc_log.close()
            except OSError:
                pass

    @classmethod
    def tearDownClass(cls):
        cls._stop_xvnc()
        shutil.rmtree(getattr(cls, "tmpdir", ""), ignore_errors=True)

    def _connect_proto(self, ssl_options):
        from xpra.net.bytestreams import SocketConnection
        from xpra.client.base.rfb_protocol import RFBClientProtocol
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=CONNECT_TIMEOUT)
        sock.settimeout(CONNECT_TIMEOUT)
        conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), "rfb-vencrypt-test", "vnc",
                                socket_options={"ssl-options": ssl_options})
        conn.target = "127.0.0.1:%i" % self.port
        conn.timeout = CONNECT_TIMEOUT
        packets = []
        done = threading.Event()

        def process_packet(_proto, packet):
            ptype = str(packet[0])
            log("client received RFB packet: %s", ptype)
            packets.append(ptype)
            if ptype in ("new-window", "connection-lost", "invalid"):
                done.set()

        proto = RFBClientProtocol(conn, process_packet, scheduler=ImmediateScheduler())
        return proto, packets, done

    def test_vencrypt_x509_handshake(self):
        # don't verify the throwaway self-signed cert: this exercises the VeNCrypt
        # negotiation + TLS upgrade, not certificate validation:
        proto, packets, done = self._connect_proto({"server-verify-mode": "none"})
        try:
            proto.start()
            self.assertTrue(done.wait(CONNECT_TIMEOUT),
                            "timed out before completing the RFB handshake, packets=%s\nXvnc log:\n%s" % (
                                packets, self._read_xvnc_log()))
            self.assertIn("new-window", packets,
                          "handshake did not reach ServerInit, packets=%s\nXvnc log:\n%s" % (
                              packets, self._read_xvnc_log()))
            # the connection must now be running over TLS (the VeNCrypt upgrade happened):
            from xpra.net.tls.connection import SSLSocketConnection
            self.assertIsInstance(proto._conn, SSLSocketConnection,
                                  "the connection was not upgraded to TLS")
        finally:
            proto.close()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
