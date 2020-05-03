#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2016-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

import errno
from ctypes import addressof, byref, c_ulong, c_char_p, c_char, c_void_p, cast, string_at

from xpra.os_util import strtobytes, memoryview_to_bytes
from xpra.net.bytestreams import Connection
from xpra.net.common import ConnectionClosedException
from xpra.platform.win32.common import (
    CloseHandle, FormatMessageSystem,
    ERROR_PIPE_BUSY, ERROR_PIPE_NOT_CONNECTED,
    IO_ERROR_STR, ERROR_BROKEN_PIPE, ERROR_IO_PENDING,
    )
from xpra.platform.win32.namedpipes.common import (
    OVERLAPPED, WAIT_STR, INVALID_HANDLE_VALUE,
    INFINITE,
    CreateEventA, CreateFileA,
    ReadFile, WriteFile, SetEvent,
    DisconnectNamedPipe, FlushFileBuffers, WaitNamedPipeA,
    GetLastError, SetNamedPipeHandleState, WaitForSingleObject, GetOverlappedResult,
    )
from xpra.platform.win32.constants import (
    FILE_FLAG_OVERLAPPED,
    GENERIC_READ, GENERIC_WRITE,
    OPEN_EXISTING, PIPE_READMODE_BYTE,
    )

from xpra.log import Logger
log = Logger("network", "named-pipe", "win32")

BUFSIZE = 65536

CONNECTION_CLOSED_ERRORS = {
    ERROR_BROKEN_PIPE           : "BROKENPIPE",
    ERROR_PIPE_NOT_CONNECTED    : "PIPE_NOT_CONNECTED",
    }
#some of these may be redundant or impossible to hit? (does not hurt I think)
for x in ("WSAENETDOWN", "WSAENETUNREACH", "WSAECONNABORTED", "WSAECONNRESET",
          "WSAENOTCONN", "WSAESHUTDOWN", "WSAETIMEDOUT", "WSAETIMEDOUT",
          "WSAEHOSTUNREACH", "WSAEDISCON"):
    CONNECTION_CLOSED_ERRORS[getattr(errno, x)] = x


class NamedPipeConnection(Connection):
    def __init__(self, name, pipe_handle, options):
        log("NamedPipeConnection(%s, %#x, %s)", name, pipe_handle, options)
        super().__init__(name, "named-pipe", options=options)
        self.pipe_handle = pipe_handle
        self.read_buffer = (c_char*BUFSIZE)()
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

    def can_retry(self, e):
        code = e.args[0]
        if code==errno.WSAEWOULDBLOCK:      #@UndefinedVariable pylint: disable=no-member
            return "WSAEWOULDBLOCK"
        #convert those to a connection closed:
        closed = CONNECTION_CLOSED_ERRORS.get(code)
        if closed:
            raise ConnectionClosedException(e) from None
        return False


    def untilConcludes(self, fn, *args, **kwargs):
        try:
            return super().untilConcludes(fn, *args, **kwargs)
        except Exception as e:
            code = GetLastError()
            log("untilConcludes(%s, ) exception: %s, error code=%s", fn, e, code, exc_info=True)
            closed = CONNECTION_CLOSED_ERRORS.get(code)
            if closed:
                return None
            raise IOError("%s: %s" % (e, code)) from None

    def read(self, n):
        return self._read(self._pipe_read, n)

    def _pipe_read(self, buf):
        read = c_ulong(0)
        r = ReadFile(self.pipe_handle, self.read_buffer_ptr, BUFSIZE, byref(read), byref(self.read_overlapped))
        log("ReadFile(..)=%i, len=%s", r, read.value)
        if not r and self.pipe_handle:
            e = GetLastError()
            if e!=ERROR_IO_PENDING:
                log("ReadFile: %s", IO_ERROR_STR.get(e, e))
                if e in CONNECTION_CLOSED_ERRORS:
                    raise ConnectionClosedException(CONNECTION_CLOSED_ERRORS[e])
            r = WaitForSingleObject(self.read_event, INFINITE)
            log("WaitForSingleObject(..)=%s, len=%s", WAIT_STR.get(r, r), read.value)
            if r and self.pipe_handle:
                raise Exception("failed to read from named pipe handle %s" % self.pipe_handle)
        if self.pipe_handle:
            if not GetOverlappedResult(self.pipe_handle, byref(self.read_overlapped), byref(read), False):
                e = GetLastError()
                if e in CONNECTION_CLOSED_ERRORS:
                    raise ConnectionClosedException(CONNECTION_CLOSED_ERRORS[e])
                raise Exception("overlapped read failed: %s" % IO_ERROR_STR.get(e, e))
        if read.value==0:
            data = None
        else:
            data = string_at(self.read_buffer_ptr, read.value)
        log("pipe_read: %i bytes", len(data or ""))          #, binascii.hexlify(s))
        return data

    def write(self, buf):
        return self._write(self._pipe_write, buf)

    def _pipe_write(self, buf):
        bbuf = memoryview_to_bytes(buf)
        size = len(bbuf)
        log("pipe_write: %i bytes", size)   #binascii.hexlify(buf))
        written = c_ulong(0)
        r = WriteFile(self.pipe_handle, c_char_p(bbuf), size, byref(written), byref(self.write_overlapped))
        log("WriteFile(..)=%s, len=%i", r, written.value)
        if not r and self.pipe_handle:
            e = GetLastError()
            if e!=ERROR_IO_PENDING:
                log("WriteFile: %s", IO_ERROR_STR.get(e, e))
                if e in CONNECTION_CLOSED_ERRORS:
                    raise ConnectionClosedException(CONNECTION_CLOSED_ERRORS[e])
            r = WaitForSingleObject(self.write_event, INFINITE)
            log("WaitForSingleObject(..)=%s, len=%i", WAIT_STR.get(r, r), written.value)
            if not self.pipe_handle:
                #closed already!
                return written.value
            if r:
                raise Exception("failed to write buffer to named pipe handle %s" % self.pipe_handle)
        if self.pipe_handle:
            if not GetOverlappedResult(self.pipe_handle, byref(self.write_overlapped), byref(written), False):
                e = GetLastError()
                raise Exception("overlapped write failed: %s" % IO_ERROR_STR.get(e, e))
            log("pipe_write: %i bytes written", written.value)
            if self.pipe_handle:
                FlushFileBuffers(self.pipe_handle)
        #SetFilePointer(self.pipe_handle, 0, FILE_BEGIN)
        return written.value

    def close(self):
        log("%s.close()", self)
        ph = self.pipe_handle
        if not ph:
            return
        self.pipe_handle = None
        def _close_err(fn, e):
            l = log.error
            try:
                code = e[0]
            except (IndexError, TypeError):
                #python3?
                code = 0
            if code==ERROR_PIPE_NOT_CONNECTED:
                l = log.debug
            l("Error: %s(%s) %i: %s", fn, ph, code, e)
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

    def get_info(self) -> dict:
        d = Connection.get_info(self)
        d["type"] = "named-pipe"
        d["closed"] = self.pipe_handle is None
        return d


def connect_to_namedpipe(pipe_name, timeout=10):
    log("connect_to_namedpipe(%s, %i)", pipe_name, timeout)
    import time
    start = time.time()
    while True:
        if time.time()-start>=timeout:
            raise Exception("timeout waiting for named pipe '%s'" % pipe_name)
        pipe_handle = CreateFileA(strtobytes(pipe_name), GENERIC_READ | GENERIC_WRITE,
                                  0, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, 0)
        log("CreateFileA(%s)=%#x", pipe_name, pipe_handle)
        if pipe_handle!=INVALID_HANDLE_VALUE:
            break
        err = GetLastError()
        log("CreateFileA(..) error=%s", err)
        if err==ERROR_PIPE_BUSY:
            if WaitNamedPipeA(pipe_name, timeout*10000)==0:
                raise Exception("timeout waiting for named pipe '%s'" % pipe_name)
        else:
            raise Exception("cannot open named pipe '%s': %s" % (pipe_name, FormatMessageSystem(err)))
    #we have a valid handle!
    dwMode = c_ulong(PIPE_READMODE_BYTE)
    r = SetNamedPipeHandleState(pipe_handle, byref(dwMode), None, None)
    log("SetNamedPipeHandleState(..)=%i", r)
    if not r:
        log.warn("Warning: SetNamedPipeHandleState failed")
    return pipe_handle
