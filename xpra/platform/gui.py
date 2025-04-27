#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import binascii
from typing import Any
from collections.abc import Callable, Iterable, Sequence

from xpra.common import noop
from xpra.platform import platform_import
from xpra.util.str_fn import bytestostr
from xpra.log import Logger

_init_done = False


def init() -> None:
    # warning: we currently call init() from multiple places to try
    # to ensure we run it as early as possible..
    global _init_done
    if not _init_done:
        _init_done = True
        do_init()


def do_init() -> None:
    """ some platforms override this """


_ready_done = False


def ready() -> None:
    global _ready_done
    if not _ready_done:
        _ready_done = True
        do_ready()


def do_ready() -> None:
    """ some platforms override this """


_default_icon = "xpra.png"


def set_default_icon(icon_filename: str) -> None:
    global _default_icon
    _default_icon = icon_filename


def get_default_icon():
    global _default_icon
    return _default_icon


def force_focus(duration=2000) -> None:
    # only implemented on macos
    assert isinstance(duration, int)


def use_stdin() -> bool:
    stdin = sys.stdin
    return bool(stdin) and stdin.isatty()


def get_clipboard_native_class() -> str:
    return ""


# defaults:
def get_native_tray_menu_helper_class() -> type | None:
    # classes that generate menus for xpra's system tray
    # let the toolkit classes use their own
    return None


def get_native_tray_classes(*_args) -> list[type]:
    # the classes we can use for our system tray:
    # let the toolkit classes use their own
    return []


def get_native_system_tray_classes(*_args) -> list[type]:
    # the classes we can use for application system tray forwarding:
    # let the toolkit classes use their own
    return []


def system_bell(*_args) -> bool:
    # let the toolkit classes use their own
    return False


def get_native_notifier_classes() -> list[type]:
    return []


def get_session_type() -> str:
    return ""


def get_xdpi() -> int:
    return -1


def get_ydpi() -> int:
    return -1


def get_monitors_info(xscale=1, yscale=1) -> dict[int, Any]:
    from xpra.gtk.info import get_monitors_info
    return get_monitors_info(xscale, yscale)


def get_icon_size() -> int:
    xdpi = get_xdpi()
    ydpi = get_ydpi()
    if xdpi > 0 and ydpi > 0:
        dpi = round((xdpi + ydpi) / 2)
    else:
        dpi = 96
    if dpi > 144:
        return 48
    if dpi > 120:
        return 32
    if dpi > 96:
        return 24
    return 16


def get_antialias_info() -> dict[str, Any]:
    return {}


def get_display_icc_info() -> dict[str, Any]:
    # per display info
    return {}


def get_icc_info() -> dict[str, Any]:
    return default_get_icc_info()


def default_get_icc_info() -> dict[str, Any]:
    ENV_ICC_DATA = os.environ.get("XPRA_ICC_DATA")
    if ENV_ICC_DATA:
        return {
            "source": "environment-override",
            "data": binascii.unhexlify(ENV_ICC_DATA),
        }
    return get_pillow_icc_info()


def get_pillow_icc_info() -> dict[str, Any]:
    screenlog = Logger("screen")
    info: dict[str, Any] = {}
    try:
        from PIL import ImageCms
        from PIL.ImageCms import get_display_profile
    except ImportError as e:
        screenlog.warn(f"Warning: unable to query color profile via Pillow: {e}")
        return info
    try:
        INTENT_STR: dict[Any, str] = {}
        for x in ("PERCEPTUAL", "RELATIVE_COLORIMETRIC", "SATURATION", "ABSOLUTE_COLORIMETRIC"):
            intent = getattr(ImageCms, "Intent", None)
            if intent:
                v = getattr(intent, x, None)
            else:
                v = getattr(ImageCms, "INTENT_%s" % x, None)
            if v:
                INTENT_STR[v] = x.lower().replace("_", "-")
        screenlog("get_icc_info() intents=%s", INTENT_STR)
        p = get_display_profile()  # NOSONAR @SuppressWarnings("python:S5727")
        screenlog("get_icc_info() display_profile=%s", p)
        if p:

            def getDefaultIntentStr(v) -> str:
                return INTENT_STR.get(v, "unknown")

            def getData(v) -> bytes:
                return v.tobytes()

            for (k, fn, conv) in (
                    ("name", "getProfileName", None),
                    ("info", "getProfileInfo", None),
                    ("copyright", "getProfileCopyright", None),
                    ("manufacturer", "getProfileManufacturer", None),
                    ("model", "getProfileModel", None),
                    ("description", "getProfileDescription", None),
                    ("default-intent", "getDefaultIntent", getDefaultIntentStr),
                    ("data", "getData", getData),
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


# global workarea for all screens
def get_workarea() -> tuple[int, int, int, int] | None:
    return None


# per monitor workareas (assuming a single screen)
def get_workareas() -> Sequence[tuple[int, int, int, int]]:
    return ()


def get_number_of_desktops() -> int:
    return 1


def get_desktop_names() -> Sequence[str]:
    return ()


def get_vrefresh() -> int:
    return -1


def get_mouse_config() -> dict:
    return {}


def get_double_click_time() -> int:
    return -1


def get_double_click_distance() -> tuple[int, int]:
    return -1, -1


def get_fixed_cursor_size() -> tuple[int, int]:
    return -1, -1


def get_cursor_size() -> int:
    return -1


def get_window_min_size() -> tuple[int, int]:
    return 0, 0


def get_window_max_size() -> tuple[int, int]:
    return 2 ** 15 - 1, 2 ** 15 - 1


def get_window_frame_size(_x, _y, _w, _h):
    return None


def get_window_frame_sizes() -> dict[str, Any]:
    return {}


def add_window_hooks(_window) -> None:
    """
    To add platform specific code to each window,
    called when the window is created.
    """


def remove_window_hooks(_window) -> None:
    """
    Remove the hooks,
    called when the window is destroyed
    """


def show_desktop(_show) -> None:
    """ If possible, show the desktop """


def set_fullscreen_monitors(_window, _fsm, _source_indication: int = 0) -> None:
    """ Only overridden by posix """


def set_shaded(_window, _shaded: bool) -> None:
    """
    GTK never exposed the 'shaded' window attribute,
    posix clients will hook it up here.
    """


def pointer_grab(_window):
    """
    Pointer grabs require platform specific code
    """
    return False


def pointer_ungrab(_window):
    """
    Pointer grabs require platform specific code
    """
    return False


def gl_check() -> str:
    return ""  # no problem


def get_wm_name() -> str:
    return ""


def can_access_display() -> bool:
    return True


def set_window_progress(window, pct: int) -> None:
    """ some platforms can indicate progress for a specific window """


take_screenshot: Callable = noop
ClientExtras = None


def get_info_base() -> dict[str, Any]:
    def fname(v):
        try:
            return v.__name__
        except AttributeError:
            return str(v)

    def fnames(flist: Iterable) -> Sequence:
        return [fname(x) for x in flist]

    return {
        "native-clipboard": get_clipboard_native_class(),
        "native_tray_menu_helper": fname(get_native_tray_menu_helper_class()),
        "native_trays": fnames(get_native_tray_classes()),
        "native_system_trays": fnames(get_native_system_tray_classes()),
        "system_bell": fname(system_bell),
        "native_notifiers": fnames(get_native_notifier_classes()),
        "wm_name": get_wm_name() or "",
        "workarea": get_workarea() or "",
        "workareas": get_workareas(),
        "monitors": get_monitors_info(),
        "desktops": get_number_of_desktops(),
        "desktop_names": get_desktop_names(),
        "session-type": get_session_type(),
        "vertical-refresh": get_vrefresh(),
        "fixed_cursor_size": get_fixed_cursor_size(),
        "cursor_size": get_cursor_size(),
        "icon_size": get_icon_size(),
        "mouse": get_mouse_config(),
        "double_click": {
            "time": get_double_click_time(),
            "distance": get_double_click_distance(),
        },
        "dpi": {
            "x": get_xdpi(),
            "y": get_ydpi(),
        },
        "antialias": get_antialias_info(),
        "icc": get_icc_info(),
        "display-icc": get_display_icc_info(),
        "window_frame": get_window_frame_sizes(),
        "can_access_display": can_access_display(),
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
                "pointer_grab", "pointer_ungrab",
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
                "get_monitors_info",
                "get_icon_size",
                "get_window_min_size", "get_window_max_size",
                "get_mouse_config",
                "get_double_click_time", "get_double_click_distance",
                "get_fixed_cursor_size", "get_cursor_size", "get_window_frame_sizes",
                "add_window_hooks", "remove_window_hooks",
                "system_bell",
                "can_access_display",
                "set_window_progress",
                "get_info",
                )


def main() -> int:
    from xpra.platform import program_context
    from xpra.util.str_fn import print_nested_dict
    from xpra.os_util import OSX, POSIX
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("GUI-Properties"):
        enable_color()
        consume_verbose_argv(sys.argv, "all")
        init()

        # naughty, but how else can I hook this up?
        if POSIX and not OSX:
            from xpra.x11.bindings.posix_display_source import init_posix_display_source
            init_posix_display_source()
        i = get_info()
        print_nested_dict(i, hex_keys=("data", "icc-data", "icc-profile"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
