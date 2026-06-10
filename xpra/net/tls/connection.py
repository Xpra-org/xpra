# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ssl
import socket
import select
from typing import Any
from threading import RLock
from collections.abc import Callable

from xpra.net.bytestreams import SocketConnection, SOCKET_TIMEOUT
from xpra.net.tls.common import get_ssl_logger
from xpra.util.env import SilenceWarningsContext

log = get_ssl_logger()


class SSLSocketConnection(SocketConnection):
    SSL_TIMEOUT_MESSAGES = ("The read operation timed out", "The write operation timed out")
    SSL_ERROR_MESSAGES = ("WRONG_VERSION_NUMBER", "UNEXPECTED_RECORD")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The read and write threads share a single OpenSSL `SSL` object, which is
        # not safe for concurrent use: under TLS 1.3 the read thread can process
        # post-handshake messages (`KeyUpdate`, `NewSessionTicket`) that mutate the
        # SSL state the write thread relies on, corrupting the record stream.
        # `_ssl_lock` serializes the actual library calls. To avoid one thread
        # blocking the other for a long time, we never hold the lock while waiting
        # for the socket: `_ssl_io` waits for readiness using select() with the lock
        # released, and only holds the lock for the (non-blocking) SSL call itself.
        self._ssl_lock = RLock()
        self._nonblocking = False

    def set_timeout(self, timeout) -> None:
        # keep the socket non-blocking: `_ssl_io` drives readiness using select()
        # and this logical timeout, rather than blocking inside the SSL call:
        self.timeout = timeout or 0

    def _ssl_io(self, isread: bool, func: Callable, *args):
        # perform an SSL socket operation serialized via `_ssl_lock`, waiting for
        # socket readiness outside the lock so a blocked reader never stalls a
        # concurrent writer (and vice versa).
        if not self._nonblocking:
            self.get_raw_socket().setblocking(False)
            self._nonblocking = True
        raw = self.get_raw_socket()
        timeout = self.timeout or SOCKET_TIMEOUT
        wait_read = isread
        while self.active:
            try:
                with self._ssl_lock:
                    return func(*args)
            except ssl.SSLWantReadError:
                # the SSL layer needs to read more from the socket before it can proceed:
                wait_read = True
            except ssl.SSLWantWriteError:
                # renegotiation / post-handshake: the SSL layer needs to write:
                wait_read = False
            except BlockingIOError:
                wait_read = isread
            # wait for readiness with the lock released, so the other direction can proceed:
            rlist = (raw, ) if wait_read else ()
            wlist = () if wait_read else (raw, )
            try:
                readable, writable, _ = select.select(rlist, wlist, (), timeout)
            except (OSError, ValueError):
                # socket closed underneath us:
                if not self.active:
                    return None
                raise
            if not readable and not writable:
                # nothing happened within the timeout: surface it so `until_concludes`
                # can re-check `is_active` and retry, matching blocking-socket behaviour:
                raise socket.timeout("timed out")
        return None

    def peek(self, n: int) -> bytes:
        return self._ssl_io(True, self._socket.recv, n, socket.MSG_PEEK)

    def read(self, n: int) -> bytes:
        buf = self._read(self._ssl_io, True, self._socket.recv, n)
        if not buf:
            return buf
        # TLS 1.3 may have more decrypted data already in the SSL buffer
        # that won't make the socket fd readable again (pending() > 0).
        # Drain it now to avoid blocking on the next recv() call.
        pending = getattr(self._socket, "pending", None)
        if pending:
            extra = pending()
            if extra > 0:
                buf += self._read(self._ssl_io, True, self._socket.recv, extra)
        return buf

    def recv_into(self, buf) -> int:
        return self._recv_into(self._ssl_io, True, self._socket.recv_into, buf)

    def write(self, buf, _packet_type: str = "") -> int:
        return self._write(self._ssl_io, False, self._socket.send, buf)

    def can_retry(self, e) -> bool | str:
        if getattr(e, "library", "") == "SSL":
            reason = getattr(e, "reason", "")
            if reason in SSLSocketConnection.SSL_ERROR_MESSAGES:
                log("SSL library error, message: %r", reason)
                return False
            log("SSL library exception: %s, reason=%r", e, reason)
        message = e.args[0]
        if message in SSLSocketConnection.SSL_TIMEOUT_MESSAGES:
            log("SSL timeout will be retried, messsage: %r", message)
            return True
        code = getattr(e, "code", None)
        if code in SSLSocketConnection.SSL_TIMEOUT_MESSAGES:
            log("SSL timeout will be retried, code: %r", code)
            return True
        return super().can_retry(e)

    def get_info(self) -> dict[str, Any]:
        i = super().get_info()
        i["ssl"] = True
        for k, fn in {
            "compression": "compression",
            "alpn-protocol": "selected_alpn_protocol",
            "npn-protocol": "selected_npn_protocol",
            "version": "version",
        }.items():
            sfn = getattr(self._socket, fn, None)
            if sfn:
                with SilenceWarningsContext(DeprecationWarning):
                    v = sfn()
                if v is not None:
                    i[k] = v
        cipher_fn = getattr(self._socket, "cipher", None)
        if cipher_fn:
            cipher = cipher_fn()
            if cipher:
                i["cipher"] = {
                    "name": cipher[0],
                    "protocol": cipher[1],
                    "bits": cipher[2],
                }
        return i
