# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any
from collections.abc import Callable, Sequence

from xpra.os_util import gi_import
from xpra.util.system import is_Wayland, is_X11
from xpra.util.str_fn import bytestostr
from xpra.util.env import envbool, get_saved_env
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("posix")
screenlog = Logger("posix", "screen")


def x11_bindings():
    if not is_X11():
        return None
    try:
        from xpra.x11 import bindings
        return bindings
    except ImportError as e:
        log("x11_bindings()", exc_info=True)
        from xpra.gtk.util import ds_inited
        if not ds_inited():
            log.warn("Warning: no X11 bindings")
            log.warn(f" {e}")
        return None


def X11WindowBindings():
    if not x11_bindings():
        return None
    from xpra.x11.bindings.window import X11WindowBindings  # @UnresolvedImport
    return X11WindowBindings()


def X11RandRBindings():
    if not x11_bindings():
        return None
    from xpra.x11.bindings.randr import RandRBindings  # @UnresolvedImport
    return RandRBindings()


device_bell: bool | None = None
RANDR_DPI = envbool("XPRA_RANDR_DPI", True)
XSETTINGS_DPI = envbool("XPRA_XSETTINGS_DPI", True)


def gl_check() -> str:
    return ""


def get_wm_name() -> str:
    return do_get_wm_name(get_saved_env())


def do_get_wm_name(env) -> str:
    wm_name = env.get("XDG_CURRENT_DESKTOP", "") or env.get("XDG_SESSION_DESKTOP") or env.get("DESKTOP_SESSION")
    if env.get("XDG_SESSION_TYPE") == "wayland" or env.get("GDK_BACKEND") == "wayland":
        if wm_name:
            wm_name += " on wayland"
        else:
            wm_name = "wayland"
    elif is_X11() and x11_bindings():
        from xpra.x11.common import get_wm_name as get_x11_wm_name
        from xpra.x11.error import xsync
        with xsync:
            wm_name = get_x11_wm_name()
    return wm_name


def get_session_type() -> str:
    if is_Wayland():
        return "Wayland"
    if is_X11():
        return "X11"
    return os.environ.get("XDG_SESSION_TYPE", "")


def _get_xsettings():
    if x11_bindings():
        from xpra.x11.error import xlog
        from xpra.x11.common import get_xsettings
        with xlog:
            return get_xsettings()
    return None


def _get_xsettings_dict() -> dict[str, Any]:
    try:
        from xpra.x11.common import xsettings_to_dict
    except ImportError:
        return {}
    return xsettings_to_dict(_get_xsettings())


def _get_xsettings_dpi() -> int:
    if XSETTINGS_DPI and x11_bindings():
        try:
            from xpra.x11.subsystem.xsettings_prop import XSettingsType
        except ImportError:
            return -1
        d = _get_xsettings_dict()
        for k, div in {
            "Xft.dpi": 1,
            "Xft/DPI": 1024,
            "gnome.Xft/DPI": 1024,
            # "Gdk/UnscaledDPI" : 1024, ??
        }.items():
            if k in d:
                value_type, value = d.get(k)
                if value_type == XSettingsType.Integer:
                    actual_value = max(10, min(1000, value // div))
                    screenlog("_get_xsettings_dpi() found %s=%s, div=%i, actual value=%i", k, value, div, actual_value)
                    return actual_value
    return -1


def _get_randr_dpi() -> tuple[int, int]:
    if RANDR_DPI and x11_bindings():
        from xpra.x11.common import get_randr_dpi
        from xpra.x11.error import xlog
        with xlog:
            return get_randr_dpi()
    return -1, -1


def get_xdpi() -> int:
    dpi = _get_xsettings_dpi()
    if dpi > 0:
        return dpi
    return _get_randr_dpi()[0]


def get_ydpi() -> int:
    dpi = _get_xsettings_dpi()
    if dpi > 0:
        return dpi
    return _get_randr_dpi()[1]


def get_icc_info() -> dict[str, Any]:
    if x11_bindings():
        from xpra.x11 import xroot_props
        return xroot_props.get_icc_data()
    return {}


def get_antialias_info() -> dict[str, Any]:
    info: dict[str, Any] = {}
    if not x11_bindings():
        return info
    try:
        from xpra.x11.subsystem.xsettings_prop import XSettingsType
        d = _get_xsettings_dict()
        for prop_name, name in {
            "Xft/Antialias": "enabled",
            "Xft/Hinting": "hinting",
        }.items():
            if prop_name in d:
                value_type, value = d.get(prop_name)
                if value_type == XSettingsType.Integer and value > 0:
                    info[name] = bool(value)

        def get_contrast(value):
            # win32 API uses numerical values:
            # (this is my best guess at translating the X11 names)
            return {
                "hintnone": 0,
                "hintslight": 1000,
                "hintmedium": 1600,
                "hintfull": 2200,
            }.get(bytestostr(value))

        for prop_name, name, convert in (
                ("Xft/HintStyle", "hintstyle", bytestostr),
                ("Xft/HintStyle", "contrast", get_contrast),
                ("Xft/RGBA", "orientation", lambda x: bytestostr(x).upper())
        ):
            if prop_name in d:
                value_type, value = d.get(prop_name)
                if value_type == XSettingsType.String:
                    cval = convert(value)
                    if cval is not None:
                        info[name] = cval
    except Exception as e:
        screenlog.warn("failed to get antialias info from xsettings: %s", e)
    screenlog("get_antialias_info()=%s", info)
    return info


def get_current_desktop() -> int:
    if x11_bindings():
        from xpra.x11 import xroot_props
        return xroot_props.get_current_desktop()
    return -1


def get_workarea() -> tuple[int, int, int, int] | None:
    if x11_bindings():
        from xpra.x11 import xroot_props
        return xroot_props.get_workarea()
    return None


def get_number_of_desktops() -> int:
    if x11_bindings():
        from xpra.x11 import xroot_props
        return xroot_props.get_number_of_desktops()
    return 0


def get_desktop_names() -> Sequence[str]:
    if x11_bindings():
        from xpra.x11 import xroot_props
        return xroot_props.get_desktop_names()
    return ("Main", )


def get_display_name() -> str:
    if x11_bindings():
        from xpra.x11.bindings.display_source import get_display_name as get_x11_display_name
        return get_x11_display_name()
    # don't want to load Gtk here just to get the name
    wd_parts = os.environ.get("WAYLAND_DISPLAY", "").split("-", 1)
    if len(wd_parts) == 2:
        return wd_parts[1]
    return ""


def get_display_size() -> tuple[int, int]:
    if x11_bindings():
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.x11.error import xsync
        with xsync:
            return X11WindowBindings().get_root_size()
    Gdk = gi_import("Gdk")
    screen = Gdk.Screen.get_default()
    if not screen:
        raise RuntimeError("unable to access the screen via Gdk")
    return screen.get_width(), screen.get_height()


def get_vrefresh() -> int:
    if x11_bindings():
        from xpra.x11.common import get_vrefresh as get_x11_vrefresh
        from xpra.x11.error import xsync
        with xsync:
            return get_x11_vrefresh()
    return -1


def get_default_cursor_size() -> tuple[int, int]:
    if x11_bindings():
        from xpra.x11.common import get_default_cursor_size as get_x11_cursor_size
        from xpra.x11.error import xsync
        with xsync:
            return get_x11_cursor_size()
    return -1, -1


def _get_xsettings_int(name: str, default_value: int) -> int:
    d = _get_xsettings_dict()
    if name not in d:
        return default_value
    value_type, value = d.get(name)
    from xpra.x11.subsystem.xsettings_prop import XSettingsType
    if value_type != XSettingsType.Integer:
        return default_value
    return value


def get_double_click_time() -> int:
    return _get_xsettings_int("Net/DoubleClickTime", -1)


def get_double_click_distance() -> tuple[int, int]:
    v = _get_xsettings_int("Net/DoubleClickDistance", -1)
    return v, v


def get_window_frame_sizes() -> dict[str, Any]:
    # for X11, have to create a window and then check the
    # _NET_FRAME_EXTENTS value after sending a _NET_REQUEST_FRAME_EXTENTS message,
    # so this is done in the gtk client instead of here...
    return {}


def system_bell(*args) -> bool:
    if not x11_bindings():
        return False
    global device_bell
    if device_bell is False:
        # failed already
        return False
    from xpra.x11.error import XError

    def x11_bell() -> None:
        from xpra.x11.common import system_bell as x11_system_bell
        if not x11_system_bell(*args):
            global device_bell
            device_bell = False

    try:
        from xpra.x11.error import xlog
        with xlog:
            x11_bell()
        return True
    except XError as e:
        log("x11_bell()", exc_info=True)
        log.error("Error using device_bell: %s", e)
        log.error(" switching native X11 bell support off")
        device_bell = False
        return False


def pointer_grab(gdk_window) -> bool:
    if x11_bindings():
        from xpra.x11.error import xlog
        with xlog:
            return X11WindowBindings().pointer_grab(gdk_window.get_xid())
    return False


def pointer_ungrab(_window) -> bool:
    if x11_bindings():
        from xpra.x11.error import xlog
        with xlog:
            return X11WindowBindings().UngrabPointer() == 0
    return False


def _send_client_message(window, message_type: str, *values) -> None:
    if not x11_bindings():
        log(f"cannot send client message {message_type} without the X11 bindings")
        return
    if window:
        xid = window.get_xid()
    else:
        from xpra.x11.bindings.core import X11CoreBindings
        xid = X11CoreBindings().get_root_xid()
    from xpra.x11.common import send_client_message
    send_client_message(xid, message_type, *values)


def show_desktop(b) -> None:
    _send_client_message(None, "_NET_SHOWING_DESKTOP", int(bool(b)))


def set_fullscreen_monitors(window, fsm, source_indication: int = 0) -> None:
    if not isinstance(fsm, (tuple, list)):
        log.warn("invalid type for fullscreen-monitors: %s", type(fsm))
        return
    if len(fsm) != 4:
        log.warn("invalid number of fullscreen-monitors: %s", len(fsm))
        return
    values = list(fsm) + [source_indication]
    _send_client_message(window, "_NET_WM_FULLSCREEN_MONITORS", *values)


def _toggle_wm_state(window, state, enabled: bool) -> None:
    if enabled:
        action = 1  # "_NET_WM_STATE_ADD"
    else:
        action = 0  # "_NET_WM_STATE_REMOVE"
    _send_client_message(window, "_NET_WM_STATE", action, state)


def set_shaded(window, shaded: bool) -> None:
    _toggle_wm_state(window, "_NET_WM_STATE_SHADED", shaded)


WINDOW_ADD_HOOKS: list[Callable] = []


def add_window_hooks(window) -> None:
    for callback in WINDOW_ADD_HOOKS:
        callback(window)
    log("add_window_hooks(%s) added %s", window, WINDOW_ADD_HOOKS)


WINDOW_REMOVE_HOOKS: list[Callable] = []


def remove_window_hooks(window):
    for callback in WINDOW_REMOVE_HOOKS:
        callback(window)
    log("remove_window_hooks(%s) added %s", window, WINDOW_REMOVE_HOOKS)


def get_info() -> dict[str, Any]:
    from xpra.platform.gui import get_info_base  # pylint: disable=import-outside-toplevel
    i = get_info_base()
    s = _get_xsettings()
    if s:
        serial, values = s
        xi = {"serial": serial}
        for _, name, value, _ in values:
            xi[bytestostr(name)] = value
        i["xsettings"] = xi
    i.setdefault("dpi", {
        "xsettings": _get_xsettings_dpi(),
        "randr": _get_randr_dpi()
    })
    return i


def main() -> int:
    try:
        from xpra.x11.gtk.display_source import init_gdk_display_source
        init_gdk_display_source()
    except ImportError:
        pass
    from xpra.platform.gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
