# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def get_interface_speed(*_args):
    return 0

def get_interface_info(*args):
    s = get_interface_speed(*args)
    if s==0:
        return {}
    return {"speed" : s}


from xpra.platform import platform_import
platform_import(globals(), "netdev_query", False,
                "get_interface_info",
                "get_interface_speed",
                )
