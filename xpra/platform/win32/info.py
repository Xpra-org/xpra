# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import ctypes
from ctypes.wintypes import DWORD

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
GetUserNameA = advapi32.GetUserNameA

def get_sys_info():
    return  {}

def get_username():
    import getpass
    return getpass.getuser()

def get_name():
    try:
        max_len = 256
        size = DWORD(max_len)
        buf = ctypes.create_string_buffer(max_len + 1)
        if not GetUserNameA(ctypes.byref(buf), ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.value
    except:
        return os.environ.get("USERNAME", "")

def get_pywin32_version():
    try:
        #the "official" way:
        import distutils.sysconfig
        pth = distutils.sysconfig.get_python_lib(plat_specific=1)
        v = open(os.path.join(pth, "pywin32.version.txt")).read().strip()
        if v:
            return v
    except:
        pass
    return None

def get_version_info():
    d = {}
    v = get_pywin32_version()
    if v:
        d["pywin32.version"] = v
    return d
