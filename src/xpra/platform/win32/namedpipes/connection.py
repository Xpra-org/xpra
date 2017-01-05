#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2016-2017 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

import ctypes
import binascii

from xpra.net.bytestreams import Connection

from xpra.log import Logger
log = Logger("network", "win32")

kernel32 = ctypes.windll.kernel32
ReadFile = kernel32.ReadFile
WriteFile = kernel32.WriteFile
CloseHandle = kernel32.CloseHandle
DisconnectNamedPipe = kernel32.DisconnectNamedPipe
FlushFileBuffers = kernel32.FlushFileBuffers

ERROR_PIPE_NOT_CONNECTED = 233
ERROR_MORE_DATA = 234


class NamedPipeConnection(Connection):
    def __init__(self, name, pipe_handle):
        Connection.__init__(self, name, "named-pipe")
        self.pipe_handle = pipe_handle

    def untilConcludes(self, *args):
        try:
            return Connection.untilConcludes(self, *args)
        except Exception as e:
            code = ctypes.get_last_error()
            if code==ERROR_PIPE_NOT_CONNECTED:
                return None
            raise IOError("%s: %s" % (e, code))

    def read(self, n):
        return self._read(self._pipe_read, n)

    def _pipe_read(self, buf):
        data = []
        hr = ERROR_MORE_DATA
        while hr==ERROR_MORE_DATA:
            hr, d = ReadFile(self.pipe_handle, 65536)
            data.append(d)
        s = b"".join(data)
        log("pipe_read: %i / %s", hr, binascii.hexlify(s))
        return s

    def write(self, buf):
        return self._write(self._pipe_write, buf)

    def _pipe_write(self, buf):
        log("pipe_write: %s", binascii.hexlify(buf))
        WriteFile(self.pipe_handle, buf)
        FlushFileBuffers(self.pipe_handle)
        #SetFilePointer(self.pipe_handle, 0, FILE_BEGIN)
        return len(buf)

    def close(self):
        def _close_err(fn, e):
            l = log.error
            code = e[0]
            if code==ERROR_PIPE_NOT_CONNECTED:
                l = log.debug
            l("Error: %s(%s) %i: %s", fn, self.pipe_handle, code, e)
        try:
            DisconnectNamedPipe(self.pipe_handle)
        except Exception as e:
            _close_err("DisconnectNamedPipe", e)
        try:
            CloseHandle(self.pipe_handle)
        except Exception as e:
            _close_err("CloseHandle", e)
        self.pipe_handle = None

    def __repr__(self):
        return "%s named-pipe" % self.target

    def get_info(self):
        d = Connection.get_info(self)
        d["type"] = "named-pipe"
        d["closed"] = self.pipe_handle is None
        return d
