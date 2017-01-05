#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2009-2017 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

import ctypes
from threading import Thread

from xpra.log import Logger
log = Logger("network", "win32")


kernel32 = ctypes.windll.kernel32
ReadFile = kernel32.ReadFile
WriteFile = kernel32.WriteFile
CloseHandle = kernel32.CloseHandle
CreateNamedPipe = kernel32.CreateNamedPipeW
ConnectNamedPipe = kernel32.ConnectNamedPipe
DisconnectNamedPipe = kernel32.DisconnectNamedPipe
FlushFileBuffers = kernel32.FlushFileBuffers

FILE_GENERIC_READ = 0x120089
FILE_GENERIC_WRITE = 0x120116
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_ALL_ACCESS = 0x1f01ff

PIPE_ACCESS_DUPLEX = 0x3
PIPE_READMODE_BYTE = 0
PIPE_UNLIMITED_INSTANCES = 0xff

ERROR_PIPE_CONNECTED = 535

SECURITY_CREATOR_SID_AUTHORITY = (0, 0, 0, 0, 0, 3)
SECURITY_WORLD_SID_AUTHORITY = (0, 0, 0, 0, 0, 1)
SECURITY_WORLD_RID = 0
SECURITY_CREATOR_OWNER_RID = 0

TIMEOUT = 6000
MAX_INSTANCES = PIPE_UNLIMITED_INSTANCES

class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.c_int),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
        ]


class NamedPipeListener(Thread):
    def __init__(self, pipe_name, new_connection_cb=None):
        self.pipe_name = pipe_name
        self.new_connection_cb = new_connection_cb
        self.exit_loop = False
        Thread.__init__(self, name="NamedPipeListener")
        self.daemon = True

    def __repr__(self):
        return "NamedPipeListener(%s)" % self.pipe_name

    def stop(self):
        log("%s.stop()", self)
        self.exit_loop = True

    def run(self):
        try:
            self.do_run()
        except Exception:
            log.error("Error: named pipe '%s'", self.pipe_name, exc_info=True)

    def do_run(self):
        while not self.exit_loop:
            pipe_handle = self.CreatePipeHandle()
            try:
                hr = ConnectNamedPipe(pipe_handle)
                assert hr in (0, ERROR_PIPE_CONNECTED), "ConnectNamedPipe returned %i" % hr
            except Exception as e:
                log.error("Error: connecting pipe handle %s:", pipe_handle)
                log.error(" %s", e)
                CloseHandle(pipe_handle)
                break
            log("new client connected to pipe: %s", hr)
            if self.exit_loop:
                break
            if self.new_connection_cb:
                self.new_connection_cb(self, pipe_handle)
            else:
                log.warn("Warning: no callback defined for new named pipe connection on %s", self.pipe_name)
                CloseHandle(pipe_handle)

    def CreatePipeHandle(self):
        sa = self.CreatePipeSecurityObject()
        try:
            return CreateNamedPipe(self.pipe_name,
                    PIPE_ACCESS_DUPLEX| FILE_FLAG_OVERLAPPED,
                    PIPE_READMODE_BYTE,
                    MAX_INSTANCES,
                    0, 0, TIMEOUT, sa)
        except Exception:
            log("failed to create named pipe '%s'", self.pipe_name)
            raise

    def CreatePipeSecurityObject(self):
        return None
        # Create a security object giving World read/write access,
        # but only "Owner" modify access.
        #sa = SECURITY_ATTRIBUTES()
        #sidEveryone = pywintypes.SID()
        #sidEveryone.Initialize(SECURITY_WORLD_SID_AUTHORITY,1)
        #sidEveryone.SetSubAuthority(0, SECURITY_WORLD_RID)
        #sidCreator = pywintypes.SID()
        #sidCreator.Initialize(SECURITY_CREATOR_SID_AUTHORITY,1)
        #sidCreator.SetSubAuthority(0, SECURITY_CREATOR_OWNER_RID)
        #acl = pywintypes.ACL()
        #acl.AddAccessAllowedAce(FILE_GENERIC_READ|FILE_GENERIC_WRITE, sidEveryone)
        #acl.AddAccessAllowedAce(FILE_ALL_ACCESS, sidCreator)
        #sa.SetSecurityDescriptorDacl(1, acl, 0)
        #return sa
