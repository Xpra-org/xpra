#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import ssl
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# SSLSocketConnection
# ---------------------------------------------------------------------------

class TestSSLSocketConnection(unittest.TestCase):

    def _make_conn(self, mock_ssl_sock=None):
        from xpra.net.tls.connection import SSLSocketConnection
        sock = mock_ssl_sock or MagicMock()
        # `_ssl_io` checks `gettimeout()` to decide whether to force non-blocking;
        # report "already non-blocking" so it leaves the (mock) socket alone:
        sock.gettimeout.return_value = 0.0
        conn = SSLSocketConnection.__new__(SSLSocketConnection)
        # minimal Connection/SocketConnection state
        conn._socket = sock
        # state normally set up by SSLSocketConnection.__init__:
        conn._ssl_lock = threading.RLock()
        conn.timeout = 0
        conn.active = True
        conn.socktype = "ssl"
        conn.socktype_wrapped = "ssl"
        conn.protocol_type = "socket"
        conn.input_bytecount = 0
        conn.input_readcount = 0
        conn.output_bytecount = 0
        conn.output_writecount = 0
        conn.options = {}
        conn.info = {}
        conn.endpoint = ("127.0.0.1", 443)
        conn.target = "127.0.0.1:443"
        conn.local = ("127.0.0.1", 12345)
        conn.remote = ("127.0.0.1", 443)
        conn.filename = None
        conn.nodelay = None
        conn.nodelay_value = None
        conn.cork = None
        return conn

    # can_retry ---

    def _make_ssl_error(self, message="", reason="", library="SSL"):
        e = OSError(message)
        e.library = library
        e.reason = reason
        e.args = (message,)
        e.code = None
        return e

    def test_can_retry_ssl_timeout_message(self):
        conn = self._make_conn()
        e = self._make_ssl_error("The read operation timed out")
        assert conn.can_retry(e) is True

    def test_can_retry_ssl_timeout_code(self):
        conn = self._make_conn()
        e = OSError("other")
        e.args = ("other",)
        e.code = "The write operation timed out"
        e.library = ""
        assert conn.can_retry(e) is True

    def test_can_retry_ssl_error_messages_returns_false(self):
        conn = self._make_conn()
        for reason in ("WRONG_VERSION_NUMBER", "UNEXPECTED_RECORD"):
            e = self._make_ssl_error(reason, reason=reason, library="SSL")
            assert conn.can_retry(e) is False, reason

    def test_can_retry_ssl_library_other_reason_falls_through(self):
        from xpra.net.common import ConnectionClosedException
        conn = self._make_conn()
        # library=SSL but reason not in SSL_ERROR_MESSAGES → falls through to super().can_retry()
        # super() calls the module-level can_retry() which raises ConnectionClosedException
        # for any OSError with an unknown (non-retryable) code.
        e = self._make_ssl_error("some error", reason="OTHER_REASON", library="SSL")
        try:
            result = conn.can_retry(e)
            # If it doesn't raise, it must return a bool/str
            assert isinstance(result, (bool, str))
        except ConnectionClosedException:
            pass  # expected: module can_retry() treated the error as a closed connection

    def test_can_retry_blocking_io_returns_true(self):
        # BlockingIOError is the canonical "safe to retry" error; verify SSL conn inherits that
        conn = self._make_conn()
        e = BlockingIOError(11, "Resource temporarily unavailable")
        result = conn.can_retry(e)
        assert result is True

    def test_can_retry_connection_reset_raises_closed(self):
        from xpra.net.common import ConnectionClosedException
        conn = self._make_conn()
        e = OSError(104, "Connection reset by peer")
        with self.assertRaises(ConnectionClosedException):
            conn.can_retry(e)

    # read ---

    def test_read_no_pending(self):
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"data"
        mock_sock.pending = None
        conn = self._make_conn(mock_sock)

        def fake_until_concludes(is_active, can_retry, fn, *args):
            return fn(*args)

        with patch("xpra.net.bytestreams.untilConcludes", side_effect=fake_until_concludes):
            data = conn.read(4)
        assert data == b"data"

    def test_read_drains_pending(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b"first", b"second"]
        mock_sock.pending.return_value = 6
        conn = self._make_conn(mock_sock)

        call_count = [0]

        def fake_until_concludes(is_active, can_retry, fn, *args):
            result = fn(*args)
            call_count[0] += 1
            return result

        with patch("xpra.net.bytestreams.untilConcludes", side_effect=fake_until_concludes):
            data = conn.read(5)
        assert data == b"firstsecond"
        assert call_count[0] == 2

    # get_info ---

    def test_get_info_includes_ssl_true(self):
        mock_sock = MagicMock()
        mock_sock.compression.return_value = None
        mock_sock.selected_alpn_protocol.return_value = None
        mock_sock.selected_npn_protocol.return_value = None
        mock_sock.version.return_value = "TLSv1.3"
        mock_sock.cipher.return_value = ("AES256-GCM-SHA384", "TLSv1.3", 256)
        conn = self._make_conn(mock_sock)
        conn.endpoint = ("127.0.0.1", 443)
        conn.target = "127.0.0.1:443"
        conn.info = {}
        conn.local = ("127.0.0.1", 12345)
        conn.remote = ("127.0.0.1", 443)
        conn.filename = None
        i = conn.get_info()
        assert i.get("ssl") is True

    def test_get_info_cipher(self):
        mock_sock = MagicMock()
        mock_sock.version.return_value = "TLSv1.3"
        mock_sock.cipher.return_value = ("TLS_AES_256", "TLSv1.3", 256)
        conn = self._make_conn(mock_sock)
        conn.endpoint = ("127.0.0.1", 443)
        conn.target = "127.0.0.1:443"
        conn.info = {}
        conn.local = ("127.0.0.1", 12345)
        conn.remote = ("127.0.0.1", 443)
        conn.filename = None
        i = conn.get_info()
        assert "cipher" in i
        assert i["cipher"]["name"] == "TLS_AES_256"


# ---------------------------------------------------------------------------
# SSLSocketConnection concurrency (issue #4918)
# ---------------------------------------------------------------------------

class TestSSLSocketConnectionConcurrency(unittest.TestCase):
    """The read and write threads share one OpenSSL object. `_ssl_io` must serialize
    the library calls with `_ssl_lock`, but must NOT hold the lock while waiting for
    the socket - otherwise a reader parked in recv() would stall a concurrent writer."""

    def _make_conn(self, fake_sock):
        from xpra.net.tls.connection import SSLSocketConnection
        conn = SSLSocketConnection.__new__(SSLSocketConnection)
        conn._socket = fake_sock
        conn._ssl_lock = threading.RLock()
        conn.timeout = 10
        conn.active = True
        return conn

    def test_lock_released_while_waiting_for_socket(self):
        # a real fd that is never readable, so select() inside _ssl_io blocks:
        r_fd, w_fd = os.pipe()
        self.addCleanup(os.close, r_fd)
        self.addCleanup(os.close, w_fd)

        class FakeSSL:
            def fileno(self):
                return r_fd

            def gettimeout(self):
                return 0.0  # already non-blocking

            def setblocking(self, _b):
                pass

            def recv_into(self, _buf):
                # always "need more data": forces _ssl_io to wait on select()
                raise ssl.SSLWantReadError()

        conn = self._make_conn(FakeSSL())

        def reader():
            # parks inside _ssl_io: recv_into -> SSLWantReadError -> select(r_fd) (never ready)
            conn._ssl_io(True, conn._socket.recv_into, bytearray(16))

        rt = threading.Thread(target=reader, daemon=True)
        rt.start()
        try:
            time.sleep(0.2)  # let the reader reach the blocking select()
            # the writer's path needs this same lock - it must be obtainable
            # even though the reader is "blocked" on the socket:
            acquired = conn._ssl_lock.acquire(timeout=2.0)
            self.assertTrue(acquired, "_ssl_lock held during the blocking wait: "
                                      "a blocked reader would stall the writer")
            conn._ssl_lock.release()
            self.assertTrue(rt.is_alive(), "reader should still be parked")
        finally:
            conn.active = False
            os.write(w_fd, b"x")  # wake the reader's select() so the thread exits
            rt.join(5)
        self.assertFalse(rt.is_alive(), "reader thread did not exit")

    def test_want_write_then_success(self):
        # an SSL write may need to read first (renegotiation): _ssl_io must wait
        # for the right direction and retry, returning the eventual result.
        r_fd, w_fd = os.pipe()
        self.addCleanup(os.close, r_fd)
        self.addCleanup(os.close, w_fd)
        os.write(w_fd, b"x")  # make the fd immediately ready so select returns at once

        calls = []

        class FakeSSL:
            def fileno(self):
                return r_fd

            def gettimeout(self):
                return 0.0  # already non-blocking

            def setblocking(self, _b):
                pass

            def send(self, data):
                calls.append(1)
                if len(calls) == 1:
                    raise ssl.SSLWantReadError()
                return len(data)

        conn = self._make_conn(FakeSSL())
        n = conn._ssl_io(False, conn._socket.send, b"payload")
        self.assertEqual(n, len(b"payload"))
        self.assertEqual(len(calls), 2)

    def test_reasserts_nonblocking_after_external_settimeout(self):
        # the socket is shared: core.py calls `settimeout()` on it (blocking mode)
        # *after* a protocol-detection peek has already used the connection. `_ssl_io`
        # must re-assert non-blocking on every call - otherwise the SSL op would block
        # inside `_ssl_lock` and stall the other direction (issue #4918 regression).
        r_fd, w_fd = os.pipe()
        self.addCleanup(os.close, r_fd)
        self.addCleanup(os.close, w_fd)
        os.write(w_fd, b"x")  # make select() return at once if it is ever reached

        # the socket starts in blocking mode with a timeout, as left by settimeout():
        state = {"timeout": 20.0, "setblocking": []}

        class FakeSSL:
            def fileno(self):
                return r_fd

            def gettimeout(self):
                return state["timeout"]

            def setblocking(self, blocking):
                state["setblocking"].append(blocking)
                state["timeout"] = None if blocking else 0.0

            def recv_into(self, _buf):
                # only safe to reach once non-blocking has been (re-)asserted:
                assert state["timeout"] == 0.0, "recv_into ran while still in blocking mode"
                return 5

        conn = self._make_conn(FakeSSL())
        n = conn._ssl_io(True, conn._socket.recv_into, bytearray(16))
        self.assertEqual(n, 5)
        self.assertIn(False, state["setblocking"], "_ssl_io did not force the socket non-blocking")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
