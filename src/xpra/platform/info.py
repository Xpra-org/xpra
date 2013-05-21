# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#default:
Keyboard = None

def get_sys_info():
    return {}

from xpra.platform import platform_import
platform_import(globals(), "info", False,
                "get_sys_info")
