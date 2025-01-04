# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os


def get_sys_info() -> dict:
    return {}


def get_name() -> str:
    try:
        from ctypes import (
            WinError, get_last_error,  # @UnresolvedImport
            c_char, byref,
        )
        from ctypes.wintypes import DWORD
        from xpra.platform.win32.common import GetUserNameA
        max_len = 256
        size = DWORD(max_len)
        # noinspection PyTypeChecker,PyCallingNonCallable
        buf = (c_char * (max_len + 1))()
        if not GetUserNameA(byref(buf), byref(size)):
            raise WinError(get_last_error())
        return buf.value[:size.value].decode()
    except Exception:
        return os.environ.get("USERNAME", "")


def get_version_info() -> dict:
    return {}
