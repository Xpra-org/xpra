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

_ready_done = False
def ready():
    global _ready_done
    if not _ready_done:
        _ready_done = True
        do_ready()

def do_ready():
    pass


#defaults:
def get_native_tray_menu_helper_classes():
    #classes that generate menus for xpra's system tray
    #let the toolkit classes use their own
    return []
def get_native_tray_classes(*args):
    #the classes we can use for our system tray:
    #let the toolkit classes use their own
    return []
def get_native_system_tray_classes(*args):
    #the classes we can use for application system tray forwarding:
    #let the toolkit classes use their own
    return []
def system_bell(*args):
    #let the toolkit classes use their own
    return False
def get_native_notifier_classes():
    return []

ClientExtras = None

from xpra.platform import platform_import
platform_import(globals(), "gui", False,
                "do_ready",
                "do_init",
                "ClientExtras",
                "get_native_tray_menu_helper_classes",
                "get_native_tray_classes",
                "get_native_system_tray_classes",
                "get_native_notifier_classes",
                "system_bell")
