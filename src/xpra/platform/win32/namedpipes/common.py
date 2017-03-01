#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2017 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from ctypes import POINTER, Structure, Union, c_void_p, c_int, c_ubyte
from ctypes.wintypes import DWORD, ULONG, HANDLE, USHORT

from xpra.platform.win32.constants import WAIT_ABANDONED, WAIT_OBJECT_0, WAIT_TIMEOUT, WAIT_FAILED

WAIT_STR = {
    WAIT_ABANDONED  : "ABANDONED",
    WAIT_OBJECT_0   : "OBJECT_0",
    WAIT_TIMEOUT    : "TIMEOUT",
    WAIT_FAILED     : "FAILED",
    }

INFINITE = 65535
INVALID_HANDLE_VALUE = -1

ERROR_PIPE_NOT_CONNECTED = 233
ERROR_MORE_DATA = 234
ERROR_BROKEN_PIPE = 109
ERROR_NO_DATA = 232
ERROR_HANDLE_EOF = 38
ERROR_IO_INCOMPLETE = 996
ERROR_IO_PENDING = 997
ERROR_MORE_DATA = 234
ERROR_CANCELLED = 1223
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_HANDLE = 6
ERROR_OPERATION_ABORTED = 995
ERROR_INVALID_PARAMETER = 87
ERROR_SUCCESS = 0
ERROR_COUNTER_TIMEOUT = 1121
ERROR_PIPE_BUSY = 231

ERROR_STR = {
    ERROR_PIPE_NOT_CONNECTED    : "PIPE_NOT_CONNECTED",
    ERROR_MORE_DATA             : "MORE_DATA",
    ERROR_BROKEN_PIPE           : "BROKEN_PIPE",
    ERROR_NO_DATA               : "NO_DATA",
    ERROR_HANDLE_EOF            : "HANDLE_EOF",
    ERROR_IO_INCOMPLETE         : "IO_INCOMPLETE",
    ERROR_IO_PENDING            : "IO_PENDING",
    ERROR_MORE_DATA             : "MORE_DATA",
    ERROR_CANCELLED             : "CANCELLED",
    ERROR_ACCESS_DENIED         : "ACCESS_DENIED",
    ERROR_INVALID_HANDLE        : "INVALID_HANDLE",
    ERROR_OPERATION_ABORTED     : "OPERATION_ABORTED",
    ERROR_INVALID_PARAMETER     : "INVALID_PARAMETER",
    ERROR_SUCCESS               : "SUCCESS",
    ERROR_COUNTER_TIMEOUT       : "COUNTER_TIMEOUT",
    ERROR_PIPE_BUSY             : "PIPE_BUSY",
    }


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

class SECURITY_ATTRIBUTES(Structure):
    _fields_ = [
        ("nLength",                 c_int),
        ("lpSecurityDescriptor",    c_void_p),
        ("bInheritHandle",          c_int),
        ]
class SECURITY_DESCRIPTOR(Structure):
    SECURITY_DESCRIPTOR_CONTROL = USHORT
    REVISION = 1
    _fields_ = [
        ('Revision',    c_ubyte),
        ('Sbz1',        c_ubyte),
        ('Control',     SECURITY_DESCRIPTOR_CONTROL),
        ('Owner',       c_void_p),
        ('Group',       c_void_p),
        ('Sacl',        c_void_p),
        ('Dacl',        c_void_p),
    ]

class TOKEN_USER(Structure):
    _fields_ = [
        ('SID',         c_void_p),
        ('ATTRIBUTES',  DWORD),
    ]
