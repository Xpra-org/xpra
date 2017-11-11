# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import absolute_import

import struct
from xpra.log import Logger
log = Logger("win32")

from libc.stdint cimport uintptr_t

cdef extern from "windows.h":
    ctypedef void *PVOID
    ctypedef PVOID HANDLE
    ctypedef HANDLE HWND
    ctypedef unsigned int UINT
    ctypedef unsigned long DWORD

    ctypedef Py_UNICODE WCHAR
    ctypedef const WCHAR* LPCWSTR
    ctypedef WCHAR* LPWSTR
    ctypedef LPWSTR LPTSTR
    ctypedef const char* LPCSTR

    int MultiByteToWideChar(UINT CodePage, DWORD dwFlags, LPCSTR lpMultiByteStr, int cbMultiByte, LPWSTR lpWideCharStr, int cchWideChar)
    int CP_ACP

cdef extern from "setappid.h" namespace "utility":
    int SetAppID(HWND hWnd, LPCWSTR pszAppID)

def set_window_group(hwnd, value):
    log("propsys.set_window_group(%i, %s)", hwnd, value)
    cdef HWND hWnd = <HWND> (<uintptr_t> hwnd)
    s = str(value).encode()
    cdef char *cstr = s
    cdef WCHAR[128] wstr
    cdef int r = MultiByteToWideChar(CP_ACP, 0, cstr, -1, wstr, 128)
    if r==0:
        log.warn("Warning: failed to convert string '%s' to wide win32 characters", s)
        log.warn(" MultiByteToWideChar returned %i", r)
        return r
    r = SetAppID(hWnd, wstr)
    log("propsys: SetAppID(%s, %s)=%i", <uintptr_t> hWnd, s, <uintptr_t> (&wstr))
    return r
