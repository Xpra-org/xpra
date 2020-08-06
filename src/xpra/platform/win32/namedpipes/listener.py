#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from ctypes.wintypes import HANDLE, DWORD
from ctypes import byref, sizeof, create_string_buffer, cast, c_void_p, c_long, pointer, POINTER
from threading import Thread

from xpra.log import Logger
from xpra.util import envbool
from xpra.os_util import strtobytes
from xpra.platform.win32.common import (
    CloseHandle, ERROR_IO_PENDING, FormatMessageSystem,
    SECURITY_ATTRIBUTES,
    )
from xpra.platform.win32.namedpipes.common import (
    OVERLAPPED, INFINITE, WAIT_STR,
    SECURITY_DESCRIPTOR, TOKEN_USER, TOKEN_PRIMARY_GROUP,
    CreateEventA, CreateNamedPipeA, ConnectNamedPipe,
    WaitForSingleObject, GetLastError,
    SetSecurityDescriptorDacl, SetSecurityDescriptorSacl,
    InitializeSecurityDescriptor,
    GetCurrentProcess, OpenProcessToken, GetTokenInformation,
    SetSecurityDescriptorOwner, SetSecurityDescriptorGroup,
    InitializeAcl, GetLengthSid,
    AddAccessAllowedAce, CreateWellKnownSid,
    SID, ACL, ACCESS_ALLOWED_ACE,
    )
from xpra.platform.win32.constants import (
    FILE_FLAG_OVERLAPPED, PIPE_ACCESS_DUPLEX, PIPE_READMODE_BYTE,
    PIPE_UNLIMITED_INSTANCES, PIPE_WAIT, PIPE_TYPE_BYTE, NMPWAIT_USE_DEFAULT_WAIT,
    WAIT_TIMEOUT,
    ACL_REVISION,
    )
log = Logger("network", "named-pipe", "win32")

UNRESTRICTED = envbool("XPRA_NAMED_PIPE_UNRESTRICTED", False)


ERROR_INSUFFICIENT_BUFFER = 122

FILE_ALL_ACCESS = 0x1f01ff
PIPE_ACCEPT_REMOTE_CLIENTS = 0
INVALID_HANDLE_VALUE = -1
ERROR_PIPE_CONNECTED = 535

TIMEOUT = 6000
BUFSIZE = 65536

ERROR_ALLOTTED_SPACE_EXCEEDED = 1344
ERROR_INVALID_ACL = 1336
ERROR_INVALID_SID = 1337
ERROR_REVISION_MISMATCH = 1306
ACL_ERRORS = {
    ERROR_ALLOTTED_SPACE_EXCEEDED   : "ERROR_ALLOTTED_SPACE_EXCEEDED",
    ERROR_INVALID_ACL               : "ERROR_INVALID_ACL",
    ERROR_INVALID_SID               : "ERROR_INVALID_SID",
    ERROR_REVISION_MISMATCH         : "ERROR_REVISION_MISMATCH",
    }

TokenUser = 0x1
TokenPrimaryGroup = 0x5

WinWorldSid = 1
WinLocalSid = 2
WinAnonymousSid = 13

STANDARD_RIGHTS_ALL = 0x001F0000
SPECIFIC_RIGHTS_ALL = 0x0000FFFF
GENERIC_ALL = 0x10000000


class NamedPipeListener(Thread):
    def __init__(self, pipe_name, new_connection_cb=None):
        log("NamedPipeListener(%s, %s)", pipe_name, new_connection_cb)
        self.pipe_name = pipe_name
        self.new_connection_cb = new_connection_cb or self.new_connection
        self.exit_loop = False
        super().__init__(name="NamedPipeListener-%s" % pipe_name)
        self.daemon = True
        self.security_attributes = None
        self.security_descriptor = None
        self.token_process = HANDLE()
        self.tokens = []
        cur_proc = GetCurrentProcess()
        log("GetCurrentProcess()=%#x", cur_proc)
        TOKEN_QUERY = 0x8
        if not OpenProcessToken(HANDLE(cur_proc), TOKEN_QUERY, byref(self.token_process)):
            raise WindowsError()    #@UndefinedVariable
        log("process=%s", self.token_process.value)

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
        tp = self.token_process
        if tp:
            self.token_process = None
            CloseHandle(tp)
        self.tokens = []
        self.security_attributes = None
        self.security_descriptor = None

    def do_run(self):
        pipe_handle = None
        while not self.exit_loop:
            if not pipe_handle:
                try:
                    pipe_handle = self.CreatePipeHandle()
                except Exception as e:
                    log("CreatePipeHandle()", exc_info=True)
                    log.error("Error: failed to create named pipe")
                    log.error(" at path '%s'", self.pipe_name)
                    log.error(" %s", e)
                    return
                log("CreatePipeHandle()=%#x", pipe_handle)
                if c_long(pipe_handle).value==INVALID_HANDLE_VALUE:
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
            if self.exit_loop:
                break
            if r==0:
                e = GetLastError()
                log("GetLastError()=%s (%i)", FormatMessageSystem(e).rstrip("\n\r"), e)
                if e==ERROR_PIPE_CONNECTED:
                    pass
                elif e==ERROR_IO_PENDING:
                    while not self.exit_loop:
                        r = WaitForSingleObject(event, INFINITE)
                        log("WaitForSingleObject(..)=%s", WAIT_STR.get(r, r))
                        if r==WAIT_TIMEOUT:
                            continue
                        if r==0:
                            break
                        log.error("Error: cannot connect to named pipe '%s'", self.pipe_name)
                        log.error(" %s", WAIT_STR.get(r, r))
                        CloseHandle(pipe_handle)
                        pipe_handle = None
                        break
                else:
                    log.error("Error: cannot connect to named pipe '%s'", self.pipe_name)
                    log.error(" error %s", e)
                    CloseHandle(pipe_handle)
                    pipe_handle = None
                if self.exit_loop:
                    break
            #from now on, the pipe_handle will be managed elsewhere:
            if pipe_handle:
                self.new_connection_cb("named-pipe", self, pipe_handle)
                pipe_handle = None
        if pipe_handle:
            self.close_handle(pipe_handle)

    def close_handle(self, pipe_handle):
        try:
            log("CloseHandle(%#x)", pipe_handle)
            CloseHandle(pipe_handle)
        except:
            log("CloseHandle(%#x)", pipe_handle, exc_info=True)

    def new_connection(self, listener, pipe_handle):
        log.info("new_connection(%s, %#x)", listener, pipe_handle)
        self.close_handle(pipe_handle)

    def CreatePipeHandle(self):
        sa = self.CreatePipeSecurityAttributes()
        log("CreateNamedPipeA using %s (UNRESTRICTED=%s)", sa, UNRESTRICTED)
        return CreateNamedPipeA(strtobytes(self.pipe_name), PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
                                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_ACCEPT_REMOTE_CLIENTS,
                                PIPE_UNLIMITED_INSTANCES, BUFSIZE, BUFSIZE, NMPWAIT_USE_DEFAULT_WAIT,
                                byref(sa))

    def GetToken(self, token_type, token_struct):
        assert self.token_process
        data_size = DWORD()
        if not GetTokenInformation(self.token_process, token_type, 0, 0, byref(data_size)):
            if GetLastError()!=ERROR_INSUFFICIENT_BUFFER:
                raise WindowsError()
        log("GetTokenInformation data size %#x", data_size.value)
        token_data = create_string_buffer(data_size.value)
        self.tokens.append(token_data)
        if not GetTokenInformation(self.token_process, token_type, byref(token_data), data_size.value, byref(data_size)):
            raise WindowsError()    #@UndefinedVariable
        token = cast(token_data, POINTER(token_struct)).contents
        return token

    def CreatePipeSecurityAttributes(self):
        user = self.GetToken(TokenUser, TOKEN_USER)
        user_SID = user.SID.contents
        log("user SID=%s, attributes=%#x", user_SID, user.ATTRIBUTES)

        group = self.GetToken(TokenPrimaryGroup, TOKEN_PRIMARY_GROUP)
        group_SID = group.PrimaryGroup.contents
        log("group SID=%s", group_SID)

        SD = SECURITY_DESCRIPTOR()
        self.security_descriptor = SD
        log("SECURITY_DESCRIPTOR=%s", SD)
        if not InitializeSecurityDescriptor(byref(SD), SECURITY_DESCRIPTOR.REVISION):
            raise WindowsError()
        log("InitializeSecurityDescriptor: %s", SD)
        if not SetSecurityDescriptorOwner(byref(SD), user.SID, False):
            raise WindowsError()
        log("SetSecurityDescriptorOwner: %s", SD)
        if not SetSecurityDescriptorGroup(byref(SD), group.PrimaryGroup, False):
            raise WindowsError()
        log("SetSecurityDescriptorGroup: %s", SD)
        SA = SECURITY_ATTRIBUTES()
        log("CreatePipeSecurityObject() SECURITY_ATTRIBUTES=%s", SA)
        if not UNRESTRICTED:
            SA.descriptor = SD
            SA.bInheritHandle = False
            return SA
        if not SetSecurityDescriptorSacl(byref(SD), False, None, False):
            raise WindowsError()
        if not SetSecurityDescriptorDacl(byref(SD), True, None, False):
            raise WindowsError()
        #this doesn't work - and I don't know why:
        #SECURITY_NT_AUTHORITY = 5
        #sia_anonymous = SID_IDENTIFIER_AUTHORITY((0, 0, 0, 0, 0, SECURITY_NT_AUTHORITY))
        #log("SID_IDENTIFIER_AUTHORITY(SECURITY_NT_AUTHORITY)=%s", sia_anonymous)
        #sid_allow = SID()
        #log("empty SID: %s", sid_allow)
        #if not AllocateAndInitializeSid(byref(sia_anonymous), 1,
        #                         SECURITY_ANONYMOUS_LOGON_RID, 0, 0, 0, 0, 0, 0, 0,
        #                         byref(sid_allow),
        #                         ):
        #    raise WindowsError()
        #    log("AllocateAndInitializeSid(..) sid_anonymous=%s", sid_allow)
        sid_allow = SID()
        sid_size = DWORD(sizeof(SID))
        sid_type = WinWorldSid
        SECURITY_MAX_SID_SIZE = 68
        assert sizeof(SID)>=SECURITY_MAX_SID_SIZE
        if not CreateWellKnownSid(sid_type, None, byref(sid_allow), byref(sid_size)):
            log.error("error=%s", GetLastError())
            raise WindowsError()
        assert sid_size.value<=SECURITY_MAX_SID_SIZE
        log("CreateWellKnownSid(..) sid_allow=%s, sid_size=%s", sid_allow, sid_size)

        acl_size = sizeof(ACL)
        acl_size += 2*(sizeof(ACCESS_ALLOWED_ACE) - sizeof(DWORD))
        acl_size += GetLengthSid(byref(sid_allow))
        acl_size += GetLengthSid(byref(user.SID.contents))
        #acl_size += GetLengthSid(user.SID)
        acl_data = create_string_buffer(acl_size)
        acl = cast(acl_data, POINTER(ACL)).contents
        log("acl_size=%s, acl_data=%s, acl=%s", acl_size, acl_data, acl)
        if not InitializeAcl(byref(acl), acl_size, ACL_REVISION):
            raise WindowsError()
        log("InitializeAcl(..) acl=%s", acl)

        rights = STANDARD_RIGHTS_ALL | SPECIFIC_RIGHTS_ALL
        add_sid = user.SID
        r = AddAccessAllowedAce(byref(acl), ACL_REVISION, rights, add_sid)
        if r==0:
            err = GetLastError()
            log("AddAccessAllowedAce(..)=%s", ACL_ERRORS.get(err, err))
            raise WindowsError()

        rights = STANDARD_RIGHTS_ALL | SPECIFIC_RIGHTS_ALL
        add_sid = byref(sid_allow)
        r = AddAccessAllowedAce(byref(acl), ACL_REVISION, rights, add_sid)
        if r==0:
            err = GetLastError()
            log("AddAccessAllowedAce(..)=%s", ACL_ERRORS.get(err, err))
            raise WindowsError()
        if not SetSecurityDescriptorDacl(byref(SD), True, byref(acl), False):
            raise WindowsError()
        SA.nLength = sizeof(SECURITY_ATTRIBUTES)
        SA.lpSecurityDescriptor = cast(pointer(SD), c_void_p)
        SA.bInheritHandle = True
        self.security_attributes = SA
        return SA


def main():
    import sys
    for verbose in ("-v", "--verbose"):
        if verbose in sys.argv:
            sys.argv.pop(verbose)
            log.enable_debug()
    pipe_name = "Xpra\\Test"
    if len(sys.argv)>1:
        pipe_name = sys.argv[1]
    l = NamedPipeListener("\\\\.\\pipe\\%s" % pipe_name)
    l.run()

if __name__ == "__main__":
    main()
