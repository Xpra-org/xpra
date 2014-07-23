# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def get_sys_info():
    try:
        from xpra.platform.xposix.info import get_sys_info as xposix_get_sys_info
        return xposix_get_sys_info()
    except:
        from xpra.log import Logger
        log = Logger("osx")
        log.error("error getting memory usage info", exc_info=True)
    return  {}

def get_pyobjc_version():
    try:
        import objc     #@UnresolvedImport
        return objc.__version__
    except:
        return None

def get_version_info():
    d = {}
    v = get_pyobjc_version()
    if v:
        d["pyobjc.version"] = v
    return d
