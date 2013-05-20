# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def get_sys_info():
    try:
        from xpra.platform.xposix.info import get_sys_info as xposix_get_sys_info
        return xposix_get_sys_info()
    except:
        from xpra.log import Logger
        log = Logger()
        log.error("error getting memory usage info", exc_info=True)
    return  {}
