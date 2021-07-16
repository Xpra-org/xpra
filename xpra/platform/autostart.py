# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def set_autostart(_enabled):
    pass

def get_status():
    return ""


from xpra.platform import platform_import
platform_import(globals(), "autostart", False,
                "set_autostart", "get_status")
