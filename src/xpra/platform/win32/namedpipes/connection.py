#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2016-2017 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

import errno
from ctypes import WinDLL, addressof, byref, c_ulong, c_char_p, c_char, c_void_p, cast, string_at

from xpra.net.bytestreams import Connection
from xpra.net.common import ConnectionClosedException
from xpra.platform.win32.namedpipes.common import OVERLAPPED, WAIT_STR, INVALID_HANDLE_VALUE, ERROR_PIPE_BUSY, ERROR_PIPE_NOT_CONNECTED, INFINITE, ERROR_STR, ERROR_BROKEN_PIPE, ERROR_IO_PENDING
from xpra.platform.win32.constants import FILE_FLAG_OVERLAPPED, GENERIC_READ, GENERIC_WRITE, OPEN_EXISTING, PIPE_READMODE_BYTE

from xpra.log import Logger
log = Logger("network", "named-pipe", "win32")

kernel32 = WinDLL("kernel32", use_last_error=True)
CreateEventA = kernel32.CreateEventA
CreateFileA = kernel32.CreateFileA
ReadFile = kernel32.ReadFile
WriteFile = kernel32.WriteFile
CloseHandle = kernel32.CloseHandle
DisconnectNamedPipe = kernel32.DisconnectNamedPipe
FlushFileBuffers = kernel32.FlushFileBuffers
WaitNamedPipeA = kernel32.WaitNamedPipeA
GetLastError = kernel32.GetLastError
SetNamedPipeHandleState = kernel32.SetNamedPipeHandleState
WaitForSingleObject = kernel32.WaitForSingleObject
GetOverlappedResult = kernel32.GetOverlappedResult

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
    def __init__(self, name, pipe_handle):
        log("NamedPipeConnection(%s, %i)", name, pipe_handle)
        Connection.__init__(self, name, "named-pipe")
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
        if code==errno.WSAEWOULDBLOCK:      #@UndefinedVariable
            return "WSAEWOULDBLOCK"
        #convert those to a connection closed:
        closed = CONNECTION_CLOSED_ERRORS.get(code)
        if closed:
            raise ConnectionClosedException(e)
        return False
        

    def untilConcludes(self, fn, *args, **kwargs):
        try:
            return Connection.untilConcludes(self, fn, *args, **kwargs)
        except Exception as e:
            code = GetLastError()
            log("untilConcludes(%s, ) exception: %s, error code=%s", fn, e, code, exc_info=True)
            if code==ERROR_PIPE_NOT_CONNECTED:
                return None
            raise IOError("%s: %s" % (e, code))

    def read(self, n):
        return self._read(self._pipe_read, n)

    def _pipe_read(self, buf):
        read = c_ulong(0)
        r = ReadFile(self.pipe_handle, self.read_buffer_ptr, BUFSIZE, byref(read), byref(self.read_overlapped))
        log("ReadFile(..)=%i, len=%s", r, read.value)
        if not r and self.pipe_handle:
            e = GetLastError()
            if e!=ERROR_IO_PENDING:
                log("ReadFile: %s", ERROR_STR.get(e, e))
            r = WaitForSingleObject(self.read_event, INFINITE)
            log("WaitForSingleObject(..)=%s, len=%s", WAIT_STR.get(r, r), read.value)
            if r and self.pipe_handle:
                raise Exception("failed to read from named pipe handle %s" % self.pipe_handle)
        if self.pipe_handle:
            if not GetOverlappedResult(self.pipe_handle, byref(self.read_overlapped), byref(read), False):
                e = GetLastError()
                if e!=ERROR_BROKEN_PIPE:
                    raise Exception("overlapped read failed: %s" % ERROR_STR.get(e, e))
        if read.value==0:
            data = None
        else:
            data = string_at(self.read_buffer_ptr, read.value)
        log("pipe_read: %i bytes", len(data or ""))          #, binascii.hexlify(s))
        return data

    def write(self, buf):
        return self._write(self._pipe_write, buf)

    def _pipe_write(self, buf):
        size = len(buf)
        log("pipe_write: %i bytes", size)   #binascii.hexlify(buf))
        written = c_ulong(0)
        r = WriteFile(self.pipe_handle, c_char_p(buf), len(buf), byref(written), byref(self.write_overlapped))
        log("WriteFile(..)=%s, len=%i", r, written.value)
        if not r and self.pipe_handle:
            e = GetLastError()
            if e!=ERROR_IO_PENDING:
                log("WriteFile: %s", ERROR_STR.get(e, e))
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
                raise Exception("overlapped write failed: %s" % ERROR_STR.get(e, e))
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
            code = e[0]
            if code==ERROR_PIPE_NOT_CONNECTED:
                l = log.debug
            l("Error: %s(%s) %i: %s", fn, ph, code, e)
        try:
            FlushFileBuffers(ph)
        except Exception as e:
            _close_err("FlushFileBuffers", e)
        try:
            DisconnectNamedPipe(ph)
        except Exception as e:
            _close_err("DisconnectNamedPipe", e)
        try:
            CloseHandle(ph)
        except Exception as e:
            _close_err("CloseHandle", e)

    def __repr__(self):
        return "named-pipe:%s" % self.target

    def get_info(self):
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
        pipe_handle = CreateFileA(pipe_name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        log("CreateFileA(%s)=%s", pipe_name, pipe_handle)
        if pipe_handle!=INVALID_HANDLE_VALUE:
            break
        if GetLastError()!=ERROR_PIPE_BUSY:
            raise Exception("cannot open named pipe '%s'" % pipe_name)
        if WaitNamedPipeA(pipe_name, timeout*10000)==0:
            raise Exception("timeout waiting for named pipe '%s'" % pipe_name)
    #we have a valid handle!
    dwMode = c_ulong(PIPE_READMODE_BYTE)
    r = SetNamedPipeHandleState(pipe_handle, byref(dwMode), None, None);
    log("SetNamedPipeHandleState(..)=%i", r)
    if not r:
        log.warn("Warning: SetNamedPipeHandleState failed")
    return pipe_handle
