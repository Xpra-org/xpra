# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#default:
Keyboard = None

def get_sys_info():
    return {}

def _get_pwd():
    try:
        import pwd
        import os
        USER_ID = os.getuid()
        return pwd.getpwuid(USER_ID)
    except:
        return None

def get_username():
    p = _get_pwd()
    if p is None:
        return ""
    return p.pw_name

def get_name():
    p = _get_pwd()
    if p is None:
        return ""
    return p.pw_gecos.replace(",", "")


from xpra.platform import platform_import
platform_import(globals(), "info", False,
                "get_sys_info",
                "get_username",
                "get_name")
