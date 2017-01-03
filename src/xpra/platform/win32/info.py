# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

def get_sys_info():
    return  {}

def get_username():
    import getpass
    return getpass.getuser()

def get_name():
    try:
        import ctypes
        from ctypes.wintypes import DWORD
        advapi32 = ctypes.windll.advapi32
        max_len = 256
        size = DWORD(max_len)
        buf = ctypes.create_string_buffer(max_len + 1)
        if not advapi32.GetUserNameA(ctypes.byref(buf), ctypes.byref(size)):
            raise ctypes.WinError()
        return buf.value
    except:
        return os.environ.get("USERNAME", "")

def get_pywin32_version():
    try:
        import win32api     #@UnresolvedImport
        assert win32api
    except:
        return None
    try:
        #the "official" way:
        import distutils.sysconfig
        pth = distutils.sysconfig.get_python_lib(plat_specific=1)
        v = open(os.path.join(pth, "pywin32.version.txt")).read().strip()
        if v:
            return v
    except:
        pass
    try:
        fixed_file_info = win32api.GetFileVersionInfo(win32api.__file__, '\\')
        v = fixed_file_info['FileVersionLS'] >> 16
        return v
    except:
        pass
    return None

def get_version_info():
    d = {}
    v = get_pywin32_version()
    if v:
        d["pywin32.version"] = v
    try:
        import wmi          #@UnresolvedImport
        d["wmi.version"] = wmi.__VERSION__
    except:
        pass
    return d
