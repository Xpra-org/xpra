#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# @PydevCodeAnalysisIgnore

import time
import errno
from ctypes import addressof, byref, c_ulong, c_char_p, c_char, c_void_p, cast, create_string_buffer, string_at
from ctypes.wintypes import DWORD, HANDLE, ULONG
from typing import Any

from xpra.util.str_fn import csv, bytestostr, strtobytes, memoryview_to_bytes
from xpra.net.bytestreams import Connection
from xpra.net.common import ConnectionClosedException
from xpra.platform.win32.common import (
    CloseHandle, FormatMessageSystem,
    CreateEventA, SetEvent,
    ERROR_PIPE_BUSY, ERROR_PIPE_NOT_CONNECTED,
    IO_ERROR_STR, ERROR_BROKEN_PIPE, ERROR_IO_PENDING,
)
from xpra.platform.win32.info import get_process_name
from xpra.platform.win32.namedpipes.common import (
    OVERLAPPED, WAIT_STR, INVALID_HANDLE, INVALID_HANDLE_VALUE,
    INFINITE,
    CreateFileA,
    ReadFile, WriteFile, DisconnectNamedPipe, FlushFileBuffers, WaitNamedPipeA,
    GetLastError, SetNamedPipeHandleState, WaitForSingleObject, GetOverlappedResult,
    GetNamedPipeClientProcessId, GetNamedPipeServerProcessId,
    GetNamedPipeClientSessionId, GetNamedPipeServerSessionId,
    GetNamedPipeClientComputerNameA,
)
from xpra.platform.win32.constants import (
    FILE_FLAG_OVERLAPPED,
    GENERIC_READ, GENERIC_WRITE,
    MAX_COMPUTERNAME_LENGTH,
    OPEN_EXISTING, PIPE_READMODE_BYTE,
)

from xpra.log import Logger

log = Logger("network", "named-pipe", "win32")

BUFSIZE = 65536

CONNECTION_CLOSED_ERRORS = {
    ERROR_BROKEN_PIPE: "BROKENPIPE",
    ERROR_PIPE_NOT_CONNECTED: "PIPE_NOT_CONNECTED",
}
# some of these may be redundant or impossible to hit? (does not hurt I think)
for x in ("WSAENETDOWN", "WSAENETUNREACH", "WSAECONNABORTED", "WSAECONNRESET",
          "WSAENOTCONN", "WSAESHUTDOWN", "WSAETIMEDOUT", "WSAETIMEDOUT",
          "WSAEHOSTUNREACH", "WSAEDISCON"):
    CONNECTION_CLOSED_ERRORS[getattr(errno, x)] = x


def query_peer_info(pipe_handle, server_side: bool) -> dict[str, Any]:
    """
    Whatever we can find out about the process at the other end of the pipe:
    its pid, the executable running as that pid, its terminal services session,
    and for clients coming in over SMB / IPC$ the computer they connected from.
    Named pipes have no address to show, this is the closest equivalent
    to the peer address logged for socket connections.
    This must be called whilst the pipe is still connected,
    and the pid it returns is only ever informational:
    pids are recycled, so it must not be used for access control
    (`ImpersonateNamedPipeClient` is the call for that)
    """
    info: dict[str, Any] = {}

    def query(fn, key: str) -> None:
        value = ULONG(0)
        if fn(pipe_handle, byref(value)):
            info[key] = int(value.value)
        else:
            log("%s(%s) failed: %s", fn.__name__, pipe_handle, IO_ERROR_STR.get(GetLastError(), GetLastError()))

    if server_side:
        query(GetNamedPipeClientProcessId, "pid")
        query(GetNamedPipeClientSessionId, "session")
        # this one is expected to fail for local clients:
        buf = create_string_buffer(MAX_COMPUTERNAME_LENGTH + 1)
        if GetNamedPipeClientComputerNameA(pipe_handle, buf, len(buf)):
            info["computer"] = bytestostr(buf.value)
    else:
        query(GetNamedPipeServerProcessId, "pid")
        query(GetNamedPipeServerSessionId, "session")
    pid = info.get("pid", 0)
    if pid and (name := get_process_name(pid)):
        info["name"] = name
    log("query_peer_info(%s, %s)=%s", pipe_handle, server_side, info)
    return info


class NamedPipeConnection(Connection):
    def __init__(self, name, pipe_handle, options, server_side=False):
        log("NamedPipeConnection(%r, %s, %s, %s)", name, pipe_handle, options, server_side)
        super().__init__(name, "named-pipe", options=options)
        self.pipe_handle = pipe_handle
        # query the peer now: this is no longer possible once it disconnects.
        # never let this stop us from setting up the connection:
        self.peer_info: dict[str, Any] = {}
        with log.trap_error("Error querying named pipe peer information"):
            self.peer_info = query_peer_info(pipe_handle, server_side)
        # noinspection PyTypeChecker,PyCallingNonCallable
        self.read_buffer = (c_char * BUFSIZE)()
        self.read_buffer_ptr = cast(addressof(self.read_buffer), c_void_p)
        self.read_event = CreateEventA(None, True, False, None)
        self.read_overlapped = OVERLAPPED()
        self.read_overlapped.hEvent = self.read_event
        self.read_overlapped.Internal = None
        self.read_overlapped.InternalHigh = None
        self.read_overlapped.union.Pointer = None
        self.write_event = CreateEventA(None, True, False, None)
        self.write_overlapped = OVERLAPPED()
        self.write_overlapped.hEvent = self.write_event
        self.write_overlapped.Internal = None
        self.write_overlapped.InternalHigh = None
        self.write_overlapped.union.Pointer = None

    def can_retry(self, e) -> bool | str:
        code = e.args[0]
        if code == errno.WSAEWOULDBLOCK:  # @UndefinedVariable pylint: disable=no-member
            return "WSAEWOULDBLOCK"
        # convert those to a connection closed:
        closed = CONNECTION_CLOSED_ERRORS.get(code)
        if closed:
            raise ConnectionClosedException(e) from None
        return False

    def untilConcludes(self, fn, *args):
        try:
            return super().untilConcludes(fn, *args)
        except Exception as e:
            code = GetLastError()
            log("untilConcludes(%s, ) exception: %s, error code=%s", fn, e, code, exc_info=True)
            closed = CONNECTION_CLOSED_ERRORS.get(code)
            if closed:
                return None
            raise OSError("%s: %s" % (e, code)) from None

    def read(self, n):
        return self._read(self._pipe_read, n)

    def _pipe_read(self, n):
        read = c_ulong(0)
        n_bytes = DWORD(min(n, BUFSIZE))
        r = ReadFile(self.pipe_handle, self.read_buffer_ptr, n_bytes, byref(read), byref(self.read_overlapped))
        log("ReadFile(%i)=%i, len=%s", n, r, read.value)
        if not r and self.pipe_handle:
            e = GetLastError()
            if e != ERROR_IO_PENDING:
                log("ReadFile: %s", IO_ERROR_STR.get(e, e))
                if e in CONNECTION_CLOSED_ERRORS:
                    raise ConnectionClosedException(CONNECTION_CLOSED_ERRORS[e])
            r = WaitForSingleObject(self.read_event, INFINITE)
            log("WaitForSingleObject(..)=%s, len=%s", WAIT_STR.get(r, r), read.value)
            if r and self.pipe_handle:
                raise RuntimeError("failed to read from named pipe handle %s" % self.pipe_handle)
        if self.pipe_handle:
            if not GetOverlappedResult(self.pipe_handle, byref(self.read_overlapped), byref(read), False):
                e = GetLastError()
                if e in CONNECTION_CLOSED_ERRORS:
                    raise ConnectionClosedException(CONNECTION_CLOSED_ERRORS[e])
                raise RuntimeError("overlapped read failed: %s" % IO_ERROR_STR.get(e, e))
        if read.value == 0:
            data = None
        else:
            data = string_at(self.read_buffer_ptr, read.value)
        log("pipe_read: %i bytes", len(data or ""))  # , binascii.hexlify(s))
        return data

    def write(self, buf, _packet_type) -> int:
        return self._write(self._pipe_write, buf)

    def _pipe_write(self, buf):
        bbuf = memoryview_to_bytes(buf)
        size = len(bbuf)
        log("pipe_write: %i bytes", size)  # binascii.hexlify(buf))
        written = c_ulong(0)
        r = WriteFile(self.pipe_handle, c_char_p(bbuf), size, byref(written), byref(self.write_overlapped))
        log("WriteFile(..)=%s, len=%i", r, written.value)
        if not r and self.pipe_handle:
            e = GetLastError()
            if e != ERROR_IO_PENDING:
                log("WriteFile: %s", IO_ERROR_STR.get(e, e))
                if e in CONNECTION_CLOSED_ERRORS:
                    raise ConnectionClosedException(CONNECTION_CLOSED_ERRORS[e])
            r = WaitForSingleObject(self.write_event, INFINITE)
            log("WaitForSingleObject(..)=%s, len=%i", WAIT_STR.get(r, r), written.value)
            if not self.pipe_handle:
                # closed already!
                return written.value
            if r:
                raise RuntimeError("failed to write buffer to named pipe handle %s" % self.pipe_handle)
        if self.pipe_handle:
            if not GetOverlappedResult(self.pipe_handle, byref(self.write_overlapped), byref(written), False):
                e = GetLastError()
                raise RuntimeError("overlapped write failed: %s" % IO_ERROR_STR.get(e, e))
            log("pipe_write: %i bytes written", written.value)
            if self.pipe_handle:
                FlushFileBuffers(self.pipe_handle)
        # SetFilePointer(self.pipe_handle, 0, FILE_BEGIN)
        return written.value

    def close(self):
        log("%s.close()", self)
        ph = self.pipe_handle
        if not ph:
            return
        self.pipe_handle = None

        def _close_err(fn, e):
            log.error("Error: %s(%s) %s", fn, ph, e)

        def logerr(fn, *args):
            try:
                fn(*args)
            except Exception as e:
                _close_err(fn, e)

        logerr(SetEvent, self.read_event)
        logerr(SetEvent, self.write_event)
        logerr(FlushFileBuffers, ph)
        logerr(DisconnectNamedPipe, ph)
        logerr(CloseHandle, ph)

    def __repr__(self):
        return self.target

    def is_local(self) -> bool:
        # named pipes are only used for connections to this host:
        return True

    def get_info(self) -> dict[str, Any]:
        d = super().get_info()
        d["type"] = "named-pipe"
        d["closed"] = self.pipe_handle is None
        if self.peer_info:
            d["peer"] = self.peer_info
        return d


def log_new_pipe_connection(conn: NamedPipeConnection, socket_info="") -> None:
    """ logs the new connection message, the named pipe equivalent of `log_new_connection` """
    log.info("New %s connection received", conn.socktype)
    peer = conn.peer_info
    attrs = [f"{key} {peer[key]}" for key in ("pid", "session") if key in peer]
    if computer := peer.get("computer"):
        # only ever set for clients connecting over SMB / IPC$:
        attrs.append(f"computer '{computer}'")
    name = peer.get("name", "")
    if name or attrs:
        details = f" ({csv(attrs)})" if attrs else ""
        # don't use `%r` for the path: it would escape every backslash
        log.info(" from %s%s", f"'{name}'" if name else "an unidentified process", details)
    if socket_info:
        log.info(" on %s", socket_info)


def connect_to_namedpipe(pipe_name: str, timeout=10) -> HANDLE:
    log("connect_to_namedpipe(%r, %i)", pipe_name, timeout)
    start = time.time()
    while True:
        if time.time() - start >= timeout:
            raise RuntimeError("timeout waiting for named pipe '%s'" % pipe_name)
        pipe_handle = CreateFileA(strtobytes(pipe_name), GENERIC_READ | GENERIC_WRITE,
                                  0, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, 0)
        log("CreateFileA(%s)=%s", pipe_name, pipe_handle)
        # Compare by integer value: in Python 3.12+ ctypes instances no longer compare
        # equal to plain Python ints, so comparing against INVALID_HANDLE (c_void_p) is
        # broken.  INVALID_HANDLE_VALUE is the plain-int sentinel.
        if pipe_handle not in (None, INVALID_HANDLE, INVALID_HANDLE_VALUE):
            break
        err = GetLastError()
        log("CreateFileA(..) error=%s", err)
        if err == ERROR_PIPE_BUSY:
            if WaitNamedPipeA(strtobytes(pipe_name), timeout * 10000) == 0:
                raise RuntimeError("timeout waiting for named pipe '%s'" % pipe_name)
        else:
            raise RuntimeError("cannot open named pipe '%s': %s" % (pipe_name, FormatMessageSystem(err)))
    # we have a valid handle!
    dw_mode = c_ulong(PIPE_READMODE_BYTE)
    r = SetNamedPipeHandleState(pipe_handle, byref(dw_mode), None, None)
    log("SetNamedPipeHandleState(..)=%i", r)
    if not r:
        log.warn("Warning: SetNamedPipeHandleState failed")
    return pipe_handle
