#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

_init_done = False
def init():
    #warning: we currently call init() from multiple places to try
    #to ensure we run it as early as possible..
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



def get_xdpi():
    return -1

def get_ydpi():
    return -1


def get_icon_size():
    xdpi = get_xdpi()
    ydpi = get_ydpi()
    if xdpi>0 and ydpi>0:
        from xpra.util import iround
        dpi = iround((xdpi + ydpi)/2.0)
    else:
        dpi = 96
    if dpi > 144:
        return 48
    elif dpi > 120:
        return 32
    elif dpi > 96:
        return 24
    else:
        return 16

def get_antialias_info():
    return {}

#global workarea for all screens
def get_workarea():
    return None

#per monitor workareas (assuming a single screen)
def get_workareas():
    return []

def get_number_of_desktops():
    return 1

def get_desktop_names():
    return []

def get_vrefresh():
    return -1

def get_double_click_time():
    return -1

def get_double_click_distance():
    return -1, -1

def get_fixed_cursor_size():
    return -1, -1

def get_cursor_size():
    return -1

def get_window_frame_size(x, y, w, h):
    return None

def get_window_frame_sizes():
    return {}


def add_window_hooks(window):
    pass

def remove_window_hooks(window):
    pass


def show_desktop(show):
    pass

def set_fullscreen_monitors(window, fsm, source_indication=0):
    pass

def set_shaded(window, shaded):
    pass


def gl_check():
    return None     #no problem

def get_menu_support_function():
    return None


take_screenshot = None
ClientExtras = None


def get_info_base():
    def fname(v):
        try:
            return v.__name__
        except:
            return str(v)
    def fnames(l):
        return [fname(x) for x in l]
    info = {
            "native_tray_menu_helpers"      : fnames(get_native_tray_menu_helper_classes()),
            "native_trays"                  : fnames(get_native_tray_classes()),
            "native_system_trays"           : fnames(get_native_system_tray_classes()),
            "system_bell"                   : fname(system_bell),
            "native_notifiers"              : fnames(get_native_notifier_classes()),
            "workarea"                      : get_workarea() or "",
            "workareas"                     : get_workareas(),
            "desktops"                      : get_number_of_desktops(),
            "desktop_names"                 : get_desktop_names(),
            "vertical-refresh"              : get_vrefresh(),
            "double_click.time"             : get_double_click_time(),
            "double_click.distance"         : get_double_click_distance(),
            "fixed_cursor_size"             : get_fixed_cursor_size(),
            "cursor_size"                   : get_cursor_size(),
            "dpi.x"                         : get_xdpi(),
            "dpi.y"                         : get_ydpi(),
            "icon_size"                     : get_icon_size(),
            }
    from xpra.util import updict
    updict(info, "antialias", get_antialias_info())
    updict(info, "window_frame", get_window_frame_sizes())
    return info

get_info = get_info_base


from xpra.platform import platform_import
platform_import(globals(), "gui", False,
                "do_ready",
                "do_init",
                "gl_check",
                "show_desktop", "set_fullscreen_monitors", "set_shaded",
                "ClientExtras",
                "take_screenshot",
                "get_menu_support_function",
                "get_native_tray_menu_helper_classes",
                "get_native_tray_classes",
                "get_native_system_tray_classes",
                "get_native_notifier_classes",
                "get_vrefresh", "get_workarea", "get_workareas",
                "get_number_of_desktops", "get_desktop_names",
                "get_antialias_info", "get_icon_size", "get_xdpi", "get_ydpi",
                "get_double_click_time", "get_double_click_distance",
                "get_fixed_cursor_size", "get_cursor_size", "get_window_frame_sizes",
                "add_window_hooks", "remove_window_hooks",
                "system_bell",
                "get_info")


def main():
    from xpra.platform import program_context
    from xpra.util import nonl
    from xpra.log import enable_color
    with program_context("GUI-Properties"):
        enable_color()
        init()
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        if verbose:
            from xpra.log import get_all_loggers
            for x in get_all_loggers():
                x.enable_debug()

        #naughty, but how else can I hook this up?
        import os
        if os.name=="posix":
            try:
                from xpra.x11.bindings import posix_display_source      #@UnusedImport
            except:
                pass    #maybe running on OSX? hope for the best..
        i = get_info()
        for k in sorted(i.keys()):
            v = i[k]
            print("* %s : %s" % (k.ljust(32), nonl(v)))


if __name__ == "__main__":
    sys.exit(main())
