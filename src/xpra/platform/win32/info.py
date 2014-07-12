# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def get_sys_info():
    return  {}

def get_username():
    import getpass
    return getpass.getuser()

def get_name():
    import win32api        #@UnresolvedImport
    return win32api.GetUserName()

def get_pywin32_version():
    try:
        #"official" way:
        import os
        import distutils.sysconfig
        pth = distutils.sysconfig.get_python_lib(plat_specific=1)
        v = open(os.path.join(pth, "pywin32.version.txt")).read().strip()
        if v:
            return v
    except:
        pass
    try:
        import win32api    #@UnresolvedImport
        fixed_file_info = win32api.GetFileVersionInfo(win32api.__file__, '\\')
        v = fixed_file_info['FileVersionLS'] >> 16
        return v
    except:
        pass

def get_version_info():
    d = {}
    v = get_pywin32_version()
    if v:
        d["pywin32.version"] = v
    return d
