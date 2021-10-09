# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os


def get_sys_info():
    return  {}

def get_name():
    try:
        from ctypes import byref, create_string_buffer, WinError, get_last_error
        from ctypes.wintypes import DWORD
        from xpra.platform.win32.common import GetUserNameA
        max_len = 256
        size = DWORD(max_len)
        buf = create_string_buffer(max_len + 1)
        if not GetUserNameA(byref(buf), byref(size)):
            raise WinError(get_last_error())
        return buf.value
    except Exception:
        return os.environ.get("USERNAME", "")

def get_version_info():
    return {}
