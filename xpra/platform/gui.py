#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import binascii

from xpra.platform import platform_import
from xpra.os_util import bytestostr
from xpra.log import Logger


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


_default_icon = "xpra.png"
def set_default_icon(icon_filename):
    global _default_icon
    _default_icon = icon_filename

def get_default_icon():
    global _default_icon
    return _default_icon


def force_focus(duration=2000):
    #only implemented on macos
    pass


def use_stdin():
    stdin = sys.stdin
    return stdin and stdin.isatty()

def get_clipboard_native_class():
    return None

#defaults:
def get_native_tray_menu_helper_class():
    #classes that generate menus for xpra's system tray
    #let the toolkit classes use their own
    return None
def get_native_tray_classes(*_args):
    #the classes we can use for our system tray:
    #let the toolkit classes use their own
    return []
def get_native_system_tray_classes(*_args):
    #the classes we can use for application system tray forwarding:
    #let the toolkit classes use their own
    return []
def system_bell(*_args):
    #let the toolkit classes use their own
    return False
def get_native_notifier_classes():
    return []


def get_session_type():
    return ""


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
    if dpi > 120:
        return 32
    if dpi > 96:
        return 24
    return 16

def get_antialias_info():
    return {}

def get_display_icc_info():
    #per display info
    return {}

def get_icc_info():
    return default_get_icc_info()

def default_get_icc_info():
    ENV_ICC_DATA = os.environ.get("XPRA_ICC_DATA")
    if ENV_ICC_DATA:
        return {
            "source"    : "environment-override",
            "data"      : binascii.unhexlify(ENV_ICC_DATA),
            }
    return get_pillow_icc_info()

def get_pillow_icc_info():
    screenlog = Logger("screen")
    info = {}
    try:
        from PIL import ImageCms
        from PIL.ImageCms import get_display_profile
        INTENT_STR = {}
        for x in ("PERCEPTUAL", "RELATIVE_COLORIMETRIC", "SATURATION", "ABSOLUTE_COLORIMETRIC"):
            v = getattr(ImageCms, "INTENT_%s" % x, None)
            if v:
                INTENT_STR[v] = x.lower().replace("_", "-")
        screenlog("get_icc_info() intents=%s", INTENT_STR)
        p = get_display_profile()
        screenlog("get_icc_info() display_profile=%s", p)
        if p:
            def getDefaultIntentStr(v):
                return INTENT_STR.get(v, "unknown")
            def getData(v):
                return v.tobytes()
            for (k, fn, conv) in (
                ("name",            "getProfileName",           None),
                ("info",            "getProfileInfo",           None),
                ("copyright",       "getProfileCopyright",      None),
                ("manufacturer",    "getProfileManufacturer",   None),
                ("model",           "getProfileModel",          None),
                ("description",     "getProfileDescription",    None),
                ("default-intent",  "getDefaultIntent",         getDefaultIntentStr),
                ("data",            "getData",                  getData),
                ):
                m = getattr(ImageCms, fn, None)
                if m is None:
                    screenlog("%s lacks %s", ImageCms, fn)
                    continue
                try:
                    v = m(p)
                    if conv:
                        v = conv(v)
                    info[k] = bytestostr(v).rstrip("\n\r")
                except Exception as e:
                    screenlog("get_icc_info()", exc_info=True)
                    screenlog("ICC profile error on %s using %s: %s", k, fn, e)
    except Exception as e:
        screenlog("get_icc_info()", exc_info=True)
        screenlog.warn("Warning: cannot query ICC profiles:")
        screenlog.warn(" %s", e)
    return info


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

def get_mouse_config():
    return {}

def get_double_click_time():
    return -1

def get_double_click_distance():
    return -1, -1

def get_fixed_cursor_size():
    return -1, -1

def get_cursor_size():
    return -1

def get_window_min_size():
    return 0, 0

def get_window_max_size():
    return 2**15-1, 2**15-1

def get_window_frame_size(_x, _y, _w, _h):
    return None

def get_window_frame_sizes():
    return {}


def add_window_hooks(_window):
    pass

def remove_window_hooks(_window):
    pass


def show_desktop(_show):
    pass

def set_fullscreen_monitors(_window, _fsm, _source_indication=0):
    pass

def set_shaded(_window, _shaded):
    pass


def gl_check():
    return None     #no problem

def get_wm_name():
    return None


def can_access_display():
    return True


take_screenshot = None
ClientExtras = None


def get_info_base():
    def fname(v):
        try:
            return v.__name__
        except AttributeError:
            return str(v)
    def fnames(l):
        return [fname(x) for x in l]
    return {
            "native-clipboard"              : fname(get_clipboard_native_class()),
            "native_tray_menu_helper"       : fname(get_native_tray_menu_helper_class()),
            "native_trays"                  : fnames(get_native_tray_classes()),
            "native_system_trays"           : fnames(get_native_system_tray_classes()),
            "system_bell"                   : fname(system_bell),
            "native_notifiers"              : fnames(get_native_notifier_classes()),
            "wm_name"                       : get_wm_name() or "",
            "workarea"                      : get_workarea() or "",
            "workareas"                     : get_workareas(),
            "desktops"                      : get_number_of_desktops(),
            "desktop_names"                 : get_desktop_names(),
            "session-type"                  : get_session_type(),
            "vertical-refresh"              : get_vrefresh(),
            "fixed_cursor_size"             : get_fixed_cursor_size(),
            "cursor_size"                   : get_cursor_size(),
            "icon_size"                     : get_icon_size(),
            "mouse"                         : get_mouse_config(),
            "double_click"                  : {
                                               "time"       : get_double_click_time(),
                                               "distance"   : get_double_click_distance(),
                                               },
            "dpi"                           : {
                                               "x"          : get_xdpi(),
                                               "y"          : get_ydpi(),
                                               },
            "antialias"                     : get_antialias_info(),
            "icc"                           : get_icc_info(),
            "display-icc"                   : get_display_icc_info(),
            "window_frame"                  : get_window_frame_sizes(),
            "can_access_display"            : can_access_display(),
            }

get_info = get_info_base


platform_import(globals(), "gui", False,
                "do_ready",
                "do_init",
                "force_focus",
                "gl_check",
                "use_stdin",
                "get_wm_name",
                "show_desktop", "set_fullscreen_monitors", "set_shaded",
                "ClientExtras",
                "take_screenshot",
                "get_clipboard_native_class",
                "get_native_tray_menu_helper_class",
                "get_native_tray_classes",
                "get_native_system_tray_classes",
                "get_native_notifier_classes",
                "get_session_type",
                "get_vrefresh", "get_workarea", "get_workareas",
                "get_number_of_desktops", "get_desktop_names",
                "get_antialias_info", "get_icc_info", "get_display_icc_info", "get_xdpi", "get_ydpi",
                "get_icon_size",
                "get_window_min_size", "get_window_max_size",
                "get_mouse_config",
                "get_double_click_time", "get_double_click_distance",
                "get_fixed_cursor_size", "get_cursor_size", "get_window_frame_sizes",
                "add_window_hooks", "remove_window_hooks",
                "system_bell",
                "can_access_display",
                "get_info")


def main():
    from xpra.platform import program_context
    from xpra.util import print_nested_dict
    from xpra.os_util import OSX, POSIX
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
        if POSIX and not OSX:
            from xpra.x11.bindings.posix_display_source import init_posix_display_source    #@UnresolvedImport
            init_posix_display_source()
        i = get_info()
        print_nested_dict(i, hex_keys=("data", "icc-data", "icc-profile"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
