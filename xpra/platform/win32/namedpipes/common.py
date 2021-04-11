#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from ctypes import POINTER, WinDLL, Structure, Union, c_void_p, c_ubyte, addressof
from ctypes.wintypes import DWORD, ULONG, HANDLE, BOOL, INT, BYTE, WORD
from ctypes.wintypes import LPCSTR

from xpra.platform.win32.constants import WAIT_ABANDONED, WAIT_OBJECT_0, WAIT_TIMEOUT, WAIT_FAILED
from xpra.platform.win32.common import LPSECURITY_ATTRIBUTES

PDWORD = POINTER(DWORD)
PHANDLE = POINTER(HANDLE)
LPDWORD = POINTER(DWORD)
PVOID = c_void_p
LPCVOID = c_void_p
LPVOID = c_void_p

WAIT_STR = {
    WAIT_ABANDONED  : "ABANDONED",
    WAIT_OBJECT_0   : "OBJECT_0",
    WAIT_TIMEOUT    : "TIMEOUT",
    WAIT_FAILED     : "FAILED",
    }

INFINITE = 65535
INVALID_HANDLE_VALUE = HANDLE(-1).value


class _inner_struct(Structure):
    _fields_ = [
        ('Offset',      DWORD),
        ('OffsetHigh',  DWORD),
        ]
class _inner_union(Union):
    _fields_  = [
        ('anon_struct', _inner_struct),
        ('Pointer',     c_void_p),
        ]
class OVERLAPPED(Structure):
    _fields_ = [
        ('Internal',        POINTER(ULONG)),
        ('InternalHigh',    POINTER(ULONG)),
        ('union',           _inner_union),
        ('hEvent',          HANDLE),
        ]
LPOVERLAPPED = POINTER(OVERLAPPED)

kernel32 = WinDLL("kernel32", use_last_error=True)
WaitForSingleObject = kernel32.WaitForSingleObject
WaitForSingleObject.argtypes = [HANDLE, DWORD]
WaitForSingleObject.restype = DWORD
CreateEventA = kernel32.CreateEventA
CreateEventA.restype = HANDLE
ReadFile = kernel32.ReadFile
ReadFile.argtypes = [HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED]
ReadFile.restype = BOOL
WriteFile = kernel32.WriteFile
WriteFile.argtypes = [HANDLE, LPCVOID, DWORD, LPDWORD, LPOVERLAPPED]
WriteFile.restype = BOOL
CreateFileA = kernel32.CreateFileA
CreateFileA.argtypes = [LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE]
CreateFileA.restype = HANDLE
WaitNamedPipeA = kernel32.WaitNamedPipeA
SetNamedPipeHandleState = kernel32.SetNamedPipeHandleState
SetNamedPipeHandleState.argtypes = [HANDLE, LPDWORD, LPDWORD, LPDWORD]
SetNamedPipeHandleState.restype = INT
GetOverlappedResult = kernel32.GetOverlappedResult
GetOverlappedResult.argtypes = [HANDLE, LPOVERLAPPED, LPDWORD, BOOL]
GetOverlappedResult.restype = BOOL
CreateNamedPipeA = kernel32.CreateNamedPipeA
CreateNamedPipeA.argtypes = [LPCSTR, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, LPSECURITY_ATTRIBUTES]
CreateNamedPipeA.restype = HANDLE
ConnectNamedPipe = kernel32.ConnectNamedPipe
ConnectNamedPipe.argtypes = [HANDLE, LPOVERLAPPED]
ConnectNamedPipe.restype = BOOL
DisconnectNamedPipe = kernel32.DisconnectNamedPipe
DisconnectNamedPipe.argtypes = [HANDLE]
DisconnectNamedPipe.restype = BOOL
FlushFileBuffers = kernel32.FlushFileBuffers
FlushFileBuffers.argtypes = [HANDLE]
FlushFileBuffers.restype = BOOL
GetLastError = kernel32.GetLastError
GetLastError.argtypes = []
GetLastError.restype = DWORD
GetCurrentProcess = kernel32.GetCurrentProcess
GetCurrentProcess.argtypes = []
GetCurrentProcess.restype = HANDLE

advapi32 = WinDLL("advapi32", use_last_error=True)
OpenProcessToken = advapi32.OpenProcessToken
OpenProcessToken.argtypes = [HANDLE, DWORD, PHANDLE]
OpenProcessToken.restype = BOOL
GetTokenInformation = advapi32.GetTokenInformation
#GetTokenInformation.argtypes = [HANDLE, TOKEN_INFORMATION_CLASS, LPVOID, DWORD, PDWORD]
GetTokenInformation.restype = BOOL
class SID_IDENTIFIER_AUTHORITY(Structure):
    _fields_ = [
        ('Value',         BYTE*6),
    ]
    def __repr__(self):
        return "<SID_IDENTIFIER_AUTHORITY: %s" % (":".join(str(v) for v in self.Value))
PSID_IDENTIFIER_AUTHORITY = POINTER(SID_IDENTIFIER_AUTHORITY)
class SID(Structure):
    _fields_ = [
        ('Revision',            BYTE),
        ('SubAuthorityCount',   BYTE),
        ('IdentifierAuthority', SID_IDENTIFIER_AUTHORITY),
        ('SubAuthority',        DWORD*16),
    ]
    def __repr__(self):
        subs = []
        for i in range(self.SubAuthorityCount):
            subs.append(self.SubAuthority[i])
        return "<SID: Revision:%i, SubAuthorityCount:%i, IdentifierAuthority:%s, SubAuthority:%s>" % (self.Revision, self.SubAuthorityCount, self.IdentifierAuthority, subs)
PSID = POINTER(SID)

class ACL(Structure):
    _fields_ = [
        ('AclRevision',         BYTE),
        ('Sbz1',                BYTE),
        ('AclSize',             WORD),
        ('AceCount',            WORD),
        ('Sbz2',                WORD),
        ]
PACL = POINTER(ACL)

class SECURITY_DESCRIPTOR(Structure):
    SECURITY_DESCRIPTOR_CONTROL = WORD
    REVISION = 1
    _fields_ = [
        ('Revision',    c_ubyte),
        ('Sbz1',        c_ubyte),
        ('Control',     SECURITY_DESCRIPTOR_CONTROL),
        ('Owner',       PSID),
        ('Group',       PSID),
        ('Sacl',        PACL),
        ('Dacl',        PACL),
    ]
    def __repr__(self):
        def c(v):
            return v.contents if v else 0
        return "<SECURITY_DESCRIPTOR at %#x: Revision:%i, Sbz1:%i, Control:%s, Owner:%s, Group:%s, Sacl=%s, Dacl=%s>" % (
            addressof(self), self.Revision, self.Sbz1, self.Control, c(self.Owner), c(self.Group), c(self.Sacl), c(self.Dacl))
PSECURITY_DESCRIPTOR = POINTER(SECURITY_DESCRIPTOR)

InitializeSecurityDescriptor = advapi32.InitializeSecurityDescriptor
SetSecurityDescriptorOwner = advapi32.SetSecurityDescriptorOwner
#don't set this argtypes, or you will get mysterious segfaults:
#SetSecurityDescriptorOwner.argtypes = [SECURITY_DESCRIPTOR, PSID, BOOL]
SetSecurityDescriptorOwner.restype = BOOL
SetSecurityDescriptorGroup = advapi32.SetSecurityDescriptorGroup
#don't set this argtypes, or you will get mysterious segfaults:
#SetSecurityDescriptorGroup.argtypes = [SECURITY_DESCRIPTOR, PSID, BOOL]
SetSecurityDescriptorGroup.restype = BOOL
SetSecurityDescriptorDacl = advapi32.SetSecurityDescriptorDacl
SetSecurityDescriptorDacl.argtypes = [PSECURITY_DESCRIPTOR, BOOL, PACL, BOOL]
SetSecurityDescriptorDacl.restype = BOOL
SetSecurityDescriptorSacl = advapi32.SetSecurityDescriptorSacl
SetSecurityDescriptorSacl.argtypes = [PSECURITY_DESCRIPTOR, BOOL, PACL, BOOL]
SetSecurityDescriptorSacl.restype = BOOL

AllocateAndInitializeSid = advapi32.AllocateAndInitializeSid
AllocateAndInitializeSid.argtypes = [PSID_IDENTIFIER_AUTHORITY, BYTE, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, PSID]
AllocateAndInitializeSid.restype = BOOL
FreeSid = advapi32.FreeSid
FreeSid.argtypes = [PSID]
FreeSid.restype = PVOID
InitializeAcl = advapi32.InitializeAcl
InitializeAcl.argtypes = [PACL, DWORD, DWORD]
InitializeAcl.restype = BOOL
GetLengthSid = advapi32.GetLengthSid
GetLengthSid.argtypes = [PSID]
GetLengthSid.restype = DWORD
CreateWellKnownSid = advapi32.CreateWellKnownSid
CreateWellKnownSid.argtypes = [WORD, PSID, PSID, PDWORD]
CreateWellKnownSid.restype = BOOL
class ACE_HEADER(Structure):
    _fields_ = [
        ('AceType',         BYTE),
        ('AceFlags',        BYTE),
        ('SidStart',        WORD),
        ]
class ACCESS_ALLOWED_ACE(Structure):
    _fields_ = [
        ('Header',          ACE_HEADER),
        ('Mask',            DWORD),
        ('SidStart',        DWORD),
        ]
AddAccessAllowedAce = advapi32.AddAccessAllowedAce
#AddAccessAllowedAce.argtypes = [PACL, DWORD, DWORD, PSID]
AddAccessAllowedAce.restype = BOOL

class TOKEN_USER(Structure):
    _fields_ = [
        ('SID',         PSID),
        ('ATTRIBUTES',  DWORD),
    ]

class TOKEN_PRIMARY_GROUP(Structure):
    _fields_ = [
        ('PrimaryGroup',    PSID),
    ]
