#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
import socket
import unittest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# SocketPeekFile
# ---------------------------------------------------------------------------

class TestSocketPeekFile(unittest.TestCase):

    def _make(self, peeked=b"", fileobj_lines=b""):
        from xpra.net.bytestreams import SocketPeekFile
        fileobj = io.BytesIO(fileobj_lines)
        updates = []
        f = SocketPeekFile(fileobj, peeked, lambda p: updates.append(p))
        return f, updates

    def test_no_peeked_delegates_to_fileobj(self):
        f, _ = self._make(b"", b"hello\nworld\n")
        line = f.readline()
        assert line == b"hello\n", repr(line)

    def test_no_peeked_limit(self):
        f, _ = self._make(b"", b"hello\nworld\n")
        line = f.readline(3)
        assert line == b"hel", repr(line)

    def test_peeked_with_newline_no_limit(self):
        f, updates = self._make(b"foo\nbar", b"")
        line = f.readline()
        assert line == b"foo\n", repr(line)
        assert f.peeked == b"bar"
        assert updates[-1] == b"bar"

    def test_peeked_with_newline_limit_before_newline(self):
        f, _ = self._make(b"foo\nbar", b"")
        line = f.readline(2)   # limit=2, newline at index 3
        assert line == b"fo", repr(line)

    def test_peeked_with_newline_limit_at_or_after_newline(self):
        f, _ = self._make(b"foo\nbar", b"")
        line = f.readline(4)   # limit >= newline+1
        assert line == b"foo\n", repr(line)

    def test_peeked_no_newline_no_limit(self):
        # peeked has no newline, no limit → reads rest from fileobj
        f, updates = self._make(b"hello", b" world\n")
        line = f.readline()
        assert line == b"hello world\n", repr(line)
        assert f.peeked == b""
        assert updates[-1] == b""

    def test_peeked_no_newline_limit_exceeds_peeked(self):
        # limit > len(peeked): reads more
        f, updates = self._make(b"hi", b" there\n")
        line = f.readline(10)
        assert line == b"hi there\n", repr(line)

    def test_peeked_no_newline_limit_within_peeked(self):
        # limit <= len(peeked), no newline → returns limit bytes from peeked
        f, _ = self._make(b"hello", b"")
        line = f.readline(3)
        assert line == b"hel", repr(line)
        assert f.peeked == b"lo"

    def test_getattr_delegates_to_fileobj(self):
        f, _ = self._make(b"", b"data")
        # 'read' is not overridden; should delegate to underlying fileobj
        assert hasattr(f, "read")
        data = f.read(4)
        assert data == b"data", repr(data)

    def test_getattr_readline_redirected_when_peeked(self):
        from xpra.net.bytestreams import SocketPeekFile
        fileobj = io.BytesIO(b"extra\n")
        updates = []
        f = SocketPeekFile(fileobj, b"peeked\n", lambda p: updates.append(p))
        # When peeked is non-empty, __getattr__("readline") returns self.readline,
        # which reads from peeked data rather than from the underlying fileobj.
        rl = f.__getattr__("readline")
        assert callable(rl)
        result = rl()
        # should return the peeked line, not "extra\n"
        assert result == b"peeked\n", repr(result)


# ---------------------------------------------------------------------------
# SocketPeekWrapper
# ---------------------------------------------------------------------------

class TestSocketPeekWrapper(unittest.TestCase):

    def _make(self, peeked=b""):
        from xpra.net.bytestreams import SocketPeekWrapper
        mock_sock = MagicMock()
        wrapper = SocketPeekWrapper(mock_sock, peeked)
        return wrapper, mock_sock

    def test_recv_peek_uses_peeked_data_when_enough(self):
        wrapper, mock_sock = self._make(b"ABCDEFGH")
        data = wrapper.recv(4, socket.MSG_PEEK)
        assert data == b"ABCD", repr(data)
        mock_sock.recv.assert_not_called()

    def test_recv_peek_reads_more_when_insufficient(self):
        wrapper, mock_sock = self._make(b"AB")
        mock_sock.recv.return_value = b"CDEF"
        data = wrapper.recv(6, socket.MSG_PEEK)
        assert data == b"ABCDEF", repr(data)
        mock_sock.recv.assert_called_once_with(4)

    def test_recv_no_peek_consumes_peeked(self):
        wrapper, mock_sock = self._make(b"HELLO")
        data = wrapper.recv(3)
        assert data == b"HEL", repr(data)
        assert wrapper.peeked == b"LO"
        mock_sock.recv.assert_not_called()

    def test_recv_into_consumes_peeked(self):
        wrapper, mock_sock = self._make(b"HELLO")
        buf = bytearray(3)
        n = wrapper.recv_into(buf)
        assert n == 3
        assert bytes(buf) == b"HEL"
        assert wrapper.peeked == b"LO"
        mock_sock.recv_into.assert_not_called()

    def test_recv_into_no_peeked_delegates(self):
        wrapper, mock_sock = self._make(b"")
        mock_sock.recv_into.return_value = 4
        buf = bytearray(4)
        n = wrapper.recv_into(buf)
        assert n == 4
        mock_sock.recv_into.assert_called_once_with(buf)

    def test_recv_no_peek_exhausts_peeked_then_reads(self):
        wrapper, mock_sock = self._make(b"AB")
        mock_sock.recv.return_value = b"CD"
        # first call: returns peeked
        data1 = wrapper.recv(4)
        assert data1 == b"AB"
        # second call: peeked is empty, delegates
        data2 = wrapper.recv(4)
        assert data2 == b"CD"

    def test_recv_no_peeked_delegates(self):
        wrapper, mock_sock = self._make(b"")
        mock_sock.recv.return_value = b"data"
        data = wrapper.recv(4)
        assert data == b"data"
        mock_sock.recv.assert_called_once_with(4, 0)

    def test_makefile_read_mode_returns_peek_file(self):
        from xpra.net.bytestreams import SocketPeekFile
        wrapper, mock_sock = self._make(b"peeked")
        mock_sock.makefile.return_value = io.BytesIO(b"")
        f = wrapper.makefile("rb")
        assert isinstance(f, SocketPeekFile)

    def test_makefile_write_mode_returns_plain(self):
        from xpra.net.bytestreams import SocketPeekFile
        wrapper, mock_sock = self._make(b"peeked")
        plain = io.BytesIO()
        mock_sock.makefile.return_value = plain
        f = wrapper.makefile("wb")
        assert not isinstance(f, SocketPeekFile)
        assert f is plain

    def test_makefile_no_peeked_returns_plain(self):
        from xpra.net.bytestreams import SocketPeekFile
        wrapper, mock_sock = self._make(b"")
        plain = io.BytesIO()
        mock_sock.makefile.return_value = plain
        f = wrapper.makefile("rb")
        assert not isinstance(f, SocketPeekFile)

    def test_getattr_delegates(self):
        wrapper, mock_sock = self._make()
        mock_sock.family = socket.AF_INET
        assert wrapper.family == socket.AF_INET

    def test_update_peek(self):
        wrapper, _ = self._make(b"old")
        wrapper._update_peek(b"new")
        assert wrapper.peeked == b"new"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class TestConnection(unittest.TestCase):

    def test_recv_into_preserves_overread_data(self):
        from xpra.net.bytestreams import Connection

        class ChunkConnection(Connection):
            def __init__(self):
                super().__init__("local", "test")
                self.chunks = [b"ABCDE"]

            def read(self, _n):
                return self.chunks.pop(0) if self.chunks else b""

        conn = ChunkConnection()
        buf = bytearray(3)
        n = conn.recv_into(buf)
        assert n == 3
        assert bytes(buf) == b"ABC"
        buf = bytearray(2)
        n = conn.recv_into(buf)
        assert n == 2
        assert bytes(buf) == b"DE"


# ---------------------------------------------------------------------------
# set_socket_timeout
# ---------------------------------------------------------------------------

class TestSetSocketTimeout(unittest.TestCase):

    def _make_socket_conn(self):
        from xpra.net.bytestreams import SocketConnection
        mock_sock = MagicMock()
        conn = SocketConnection.__new__(SocketConnection)
        conn._socket = mock_sock
        conn.active = True
        conn.socktype = "tcp"
        conn.socktype_wrapped = "tcp"
        conn.options = {}
        conn.input_bytecount = 0
        conn.input_readcount = 0
        conn.output_bytecount = 0
        conn.output_writecount = 0
        conn.cork = False
        conn.nodelay = False
        conn.nodelay_value = None
        conn.cork_value = None
        return conn, mock_sock

    def test_socket_connection_sets_timeout(self):
        from xpra.net.bytestreams import set_socket_timeout
        conn, mock_sock = self._make_socket_conn()
        set_socket_timeout(conn, 5.0)
        mock_sock.settimeout.assert_called_once_with(5.0)

    def test_socket_connection_none_timeout(self):
        from xpra.net.bytestreams import set_socket_timeout
        conn, mock_sock = self._make_socket_conn()
        set_socket_timeout(conn, None)
        mock_sock.settimeout.assert_called_once_with(None)

    def test_non_socket_connection_ignored(self):
        from xpra.net.bytestreams import set_socket_timeout
        # passing something that is not a SocketConnection should be silent
        set_socket_timeout(MagicMock(), 1.0)


# ---------------------------------------------------------------------------
# log_new_connection
# ---------------------------------------------------------------------------

class TestLogNewConnection(unittest.TestCase):

    def _make_tcp_conn(self, peername=("10.0.0.1", 9999), sockname=("127.0.0.1", 10000)):
        from xpra.net.bytestreams import SocketConnection
        mock_sock = MagicMock()
        mock_sock.getpeername.return_value = peername
        mock_sock.getsockname.return_value = sockname
        conn = SocketConnection.__new__(SocketConnection)
        conn._socket = mock_sock
        conn.remote = peername
        conn.socktype = "tcp"
        conn.socktype_wrapped = "tcp"
        conn.active = True
        return conn

    def test_tcp_with_peername(self):
        from xpra.net.bytestreams import log_new_connection
        conn = self._make_tcp_conn()
        # must not raise
        log_new_connection(conn, socket_info="")

    def test_tcp_with_socket_info(self):
        from xpra.net.bytestreams import log_new_connection
        conn = self._make_tcp_conn()
        log_new_connection(conn, socket_info="0.0.0.0:10000")

    def test_unix_socket_type(self):
        from xpra.net.bytestreams import SocketConnection, log_new_connection
        mock_sock = MagicMock()
        mock_sock.getpeername.side_effect = OSError("not connected")
        mock_sock.getsockname.return_value = "/tmp/test.sock"
        conn = SocketConnection.__new__(SocketConnection)
        conn._socket = mock_sock
        conn.remote = ""
        conn.socktype = "socket"
        conn.socktype_wrapped = "socket"
        conn.active = True
        log_new_connection(conn, socket_info="/tmp/test.sock")

    def test_peername_error_falls_back_to_address(self):
        from xpra.net.bytestreams import SocketConnection, log_new_connection
        mock_sock = MagicMock()
        mock_sock.getpeername.side_effect = OSError("not available")
        mock_sock.getsockname.return_value = ("127.0.0.1", 10000)
        conn = SocketConnection.__new__(SocketConnection)
        conn._socket = mock_sock
        conn.remote = ("192.168.1.1", 5555)
        conn.socktype = "tcp"
        conn.socktype_wrapped = "tcp"
        conn.active = True
        log_new_connection(conn)

    def test_getsockname_attribute_error(self):
        from xpra.net.bytestreams import SocketConnection, log_new_connection
        mock_sock = MagicMock()
        mock_sock.getpeername.return_value = ("10.0.0.1", 9999)
        del mock_sock.getsockname
        conn = SocketConnection.__new__(SocketConnection)
        conn._socket = mock_sock
        conn.remote = ("10.0.0.1", 9999)
        conn.socktype = "ssh"
        conn.socktype_wrapped = "ssh"
        conn.active = True
        log_new_connection(conn)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
