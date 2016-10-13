#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2009-2016 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from threading import Thread

from xpra.log import Logger
log = Logger("network", "win32")


import pywintypes, winerror            #@UnresolvedImport
from win32file import CloseHandle, FILE_GENERIC_READ, FILE_GENERIC_WRITE, FILE_FLAG_OVERLAPPED, FILE_ALL_ACCESS             #@UnresolvedImport
from win32pipe import CreateNamedPipe, ConnectNamedPipe, PIPE_ACCESS_DUPLEX, PIPE_READMODE_BYTE, PIPE_UNLIMITED_INSTANCES   #@UnresolvedImport
from win32api import error            #@UnresolvedImport
from ntsecuritycon import SECURITY_CREATOR_SID_AUTHORITY, SECURITY_WORLD_SID_AUTHORITY, SECURITY_WORLD_RID, SECURITY_CREATOR_OWNER_RID    #@UnresolvedImport


TIMEOUT = 6000
MAX_INSTANCES = PIPE_UNLIMITED_INSTANCES


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
                assert hr in (0, winerror.ERROR_PIPE_CONNECTED), "ConnectNamedPipe returned %i" % hr
            except error as e:
                log.error("error connecting pipe: %s", e)
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
        # Create a security object giving World read/write access,
        # but only "Owner" modify access.
        sa = pywintypes.SECURITY_ATTRIBUTES()
        sidEveryone = pywintypes.SID()
        sidEveryone.Initialize(SECURITY_WORLD_SID_AUTHORITY,1)
        sidEveryone.SetSubAuthority(0, SECURITY_WORLD_RID)
        sidCreator = pywintypes.SID()
        sidCreator.Initialize(SECURITY_CREATOR_SID_AUTHORITY,1)
        sidCreator.SetSubAuthority(0, SECURITY_CREATOR_OWNER_RID)
        acl = pywintypes.ACL()
        acl.AddAccessAllowedAce(FILE_GENERIC_READ|FILE_GENERIC_WRITE, sidEveryone)
        acl.AddAccessAllowedAce(FILE_ALL_ACCESS, sidCreator)
        sa.SetSecurityDescriptorDacl(1, acl, 0)
        return sa
