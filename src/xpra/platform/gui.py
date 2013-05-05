# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


_init_done = False
def init():
    global _init_done
    if not _init_done:
        _init_done = True
        do_init()

def do_init():
    pass

#defaults:
def make_tray_menu(client):
    #let the toolkit classes use their own
    return None
def make_native_tray(*args):
    #let the toolkit classes use their own
    return None
def system_bell(*args):
    #let the toolkit classes use their own
    return False

from xpra.platform import platform_import
platform_import(globals(), "gui", False,
                "make_tray_menu",
                "make_native_tray",
                "system_bell")
