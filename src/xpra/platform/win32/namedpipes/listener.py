#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2017 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

import ctypes
from threading import Thread

from xpra.log import Logger
from xpra.platform.win32.namedpipes.common import OVERLAPPED, INFINITE, WAIT_STR
from xpra.platform.win32.constants import FILE_FLAG_OVERLAPPED, PIPE_ACCESS_DUPLEX, PIPE_READMODE_BYTE, PIPE_UNLIMITED_INSTANCES, PIPE_WAIT, PIPE_TYPE_BYTE, NMPWAIT_USE_DEFAULT_WAIT
log = Logger("network", "named-pipe", "win32")


kernel32 = ctypes.windll.kernel32
WaitForSingleObject = kernel32.WaitForSingleObject
CreateEventA = kernel32.CreateEventA
ReadFile = kernel32.ReadFile
WriteFile = kernel32.WriteFile
CloseHandle = kernel32.CloseHandle
CreateNamedPipeA = kernel32.CreateNamedPipeA
ConnectNamedPipe = kernel32.ConnectNamedPipe
DisconnectNamedPipe = kernel32.DisconnectNamedPipe
FlushFileBuffers = kernel32.FlushFileBuffers
GetLastError = kernel32.GetLastError

FILE_ALL_ACCESS = 0x1f01ff
PIPE_ACCEPT_REMOTE_CLIENTS = 0
INVALID_HANDLE_VALUE = -1
ERROR_PIPE_CONNECTED = 535

TIMEOUT = 6000
BUFSIZE = 65536


class NamedPipeListener(Thread):
    def __init__(self, pipe_name, new_connection_cb=None):
        self.pipe_name = pipe_name
        self.new_connection_cb = new_connection_cb
        self.exit_loop = False
        Thread.__init__(self, name="NamedPipeListener-%s" % pipe_name)
        self.daemon = True

    def __repr__(self):
        return "NamedPipeListener(%s)" % self.pipe_name

    def stop(self):
        log("%s.stop()", self)
        self.exit_loop = True

    def run(self):
        log("%s.run()", self)
        try:
            self.do_run()
        except Exception:
            log.error("Error: named pipe '%s'", self.pipe_name, exc_info=True)

    def do_run(self):
        while not self.exit_loop:
            pipe_handle = None
            try:
                pipe_handle = self.CreatePipeHandle()
            except Exception:
                log.error("Error: failed to create named pipe '%s'", self.pipe_name)
                return
            log("CreatePipeHandle()=%s", pipe_handle)
            if pipe_handle==INVALID_HANDLE_VALUE:
                log.error("Error: invalid handle for named pipe '%s'", self.pipe_name)
                return
            event = CreateEventA(None, True, False, None)
            overlapped = OVERLAPPED()
            overlapped.hEvent = event
            overlapped.Internal = None
            overlapped.InternalHigh = None
            overlapped.union.Pointer = None
            r = ConnectNamedPipe(pipe_handle, overlapped)
            log("ConnectNamedPipe()=%s", r)
            if not r and not self.exit_loop:
                r = WaitForSingleObject(event, INFINITE)
                log("WaitForSingleObject(..)=%s", WAIT_STR.get(r, r))
                if r:
                    log.error("Error: cannot connect to named pipe '%s'", self.pipe_name)
                    CloseHandle(pipe_handle)
                    continue
            if self.exit_loop:
                CloseHandle(pipe_handle)
                break
            if r==0 and False:
                if GetLastError()==ERROR_PIPE_CONNECTED:
                    pass
                else:
                    log.error("Error: cannot connect to named pipe '%s'", self.pipe_name)
                    CloseHandle(pipe_handle)
                    continue
            #from now on, the pipe_handle will be managed elsewhere:
            self.new_connection_cb(self, pipe_handle)

    def CreatePipeHandle(self):
        sa = self.CreatePipeSecurityObject()
        return CreateNamedPipeA(self.pipe_name, PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
                                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_ACCEPT_REMOTE_CLIENTS,
                                PIPE_UNLIMITED_INSTANCES, BUFSIZE, BUFSIZE, NMPWAIT_USE_DEFAULT_WAIT, sa)

    def CreatePipeSecurityObject(self):
        #TODO: re-implement using ctypes
        return None
