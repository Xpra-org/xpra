#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2017 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

import ctypes
from ctypes.wintypes import HANDLE, DWORD
from threading import Thread

from xpra.log import Logger
from xpra.util import envbool
from xpra.platform.win32.namedpipes.common import OVERLAPPED, INFINITE, WAIT_STR, SECURITY_DESCRIPTOR, SECURITY_ATTRIBUTES, TOKEN_USER
from xpra.platform.win32.constants import FILE_FLAG_OVERLAPPED, PIPE_ACCESS_DUPLEX, PIPE_READMODE_BYTE, PIPE_UNLIMITED_INSTANCES, PIPE_WAIT, PIPE_TYPE_BYTE, NMPWAIT_USE_DEFAULT_WAIT
log = Logger("network", "named-pipe", "win32")

UNRESTRICTED = envbool("XPRA_NAMED_PIPE_UNRESTRICTED", False)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
WaitForSingleObject = kernel32.WaitForSingleObject
CreateEventA = kernel32.CreateEventA
CreateEventA.restype = HANDLE
ReadFile = kernel32.ReadFile
WriteFile = kernel32.WriteFile
CloseHandle = kernel32.CloseHandle
CreateNamedPipeA = kernel32.CreateNamedPipeA
CreateNamedPipeA.restype = HANDLE
ConnectNamedPipe = kernel32.ConnectNamedPipe
DisconnectNamedPipe = kernel32.DisconnectNamedPipe
FlushFileBuffers = kernel32.FlushFileBuffers
GetLastError = kernel32.GetLastError
GetCurrentProcess = kernel32.GetCurrentProcess
GetCurrentProcess.restype = HANDLE
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
InitializeSecurityDescriptor = advapi32.InitializeSecurityDescriptor
SetSecurityDescriptorOwner = advapi32.SetSecurityDescriptorOwner
SetSecurityDescriptorDacl = advapi32.SetSecurityDescriptorDacl
OpenProcessToken = advapi32.OpenProcessToken
GetTokenInformation = advapi32.GetTokenInformation

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
        if UNRESTRICTED:
            sa = self.CreateUnrestrictedPipeSecurityObject()
        else:
            sa = self.CreatePipeSecurityObject()
        return CreateNamedPipeA(self.pipe_name, PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
                                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_ACCEPT_REMOTE_CLIENTS,
                                PIPE_UNLIMITED_INSTANCES, BUFSIZE, BUFSIZE, NMPWAIT_USE_DEFAULT_WAIT, sa)

    def CreateUnrestrictedPipeSecurityObject(self):
        SD = SECURITY_DESCRIPTOR()
        InitializeSecurityDescriptor(ctypes.byref(SD), SECURITY_DESCRIPTOR.REVISION)
        if SetSecurityDescriptorDacl(ctypes.byref(SD), True, None, False)==0:
            raise WindowsError()
        SA = SECURITY_ATTRIBUTES()
        SA.descriptor = SD
        SA.bInheritHandle = False
        return SA

    def CreatePipeSecurityObject(self):
        TOKEN_QUERY = 0x8
        cur_proc = GetCurrentProcess()
        log("CreatePipeSecurityObject() GetCurrentProcess()=%s", cur_proc)
        process = HANDLE()
        if OpenProcessToken(HANDLE(cur_proc), TOKEN_QUERY, ctypes.byref(process))==0:
            raise WindowsError()
        log("CreatePipeSecurityObject() process=%s", process.value)
        data_size = DWORD()
        GetTokenInformation(process, TOKEN_QUERY, 0, 0, ctypes.byref(data_size))
        log("CreatePipeSecurityObject() GetTokenInformation data size%s", data_size.value)
        data = ctypes.create_string_buffer(data_size.value)
        if GetTokenInformation(process, TOKEN_QUERY, ctypes.byref(data), ctypes.sizeof(data), ctypes.byref(data_size))==0:
            raise WindowsError()
        user = ctypes.cast(data, ctypes.POINTER(TOKEN_USER)).contents
        log("CreatePipeSecurityObject() user: SID=%s, attributes=%#x", user.SID, user.ATTRIBUTES)
        SD = SECURITY_DESCRIPTOR()
        InitializeSecurityDescriptor(ctypes.byref(SD), SECURITY_DESCRIPTOR.REVISION)
        SetSecurityDescriptorOwner(ctypes.byref(SD), user.SID, 0)
        SA = SECURITY_ATTRIBUTES()
        SA.descriptor = SD
        SA.bInheritHandle = False
        return SA
