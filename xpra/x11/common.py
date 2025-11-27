# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Callable

from xpra.util.env import envbool
from xpra.util.str_fn import bytestostr
from xpra.log import Logger

log = Logger("x11")


class Unmanageable(Exception):
    pass


# gtk will inject its lookup function here
# (which we can eventually remove)
def nolookup(_xid: int):
    return object()


get_pywindow = nolookup


REPR_FUNCTIONS: dict[type, Callable[[Any], Any]] = {}


_NET_WM_STATE_REMOVE = 0
_NET_WM_STATE_ADD = 1
_NET_WM_STATE_TOGGLE = 2
STATE_STRING: dict[int, str] = {
    _NET_WM_STATE_REMOVE: "REMOVE",
    _NET_WM_STATE_ADD: "ADD",
    _NET_WM_STATE_TOGGLE: "TOGGLE",
}


DEFAULT_NET_SUPPORTED: list[str] = [
    "_NET_SUPPORTED",  # a bit redundant, perhaps...
    "_NET_SUPPORTING_WM_CHECK",
    "_NET_WM_FULL_PLACEMENT",
    "_NET_WM_HANDLED_ICONS",
    "_NET_CLIENT_LIST",
    "_NET_CLIENT_LIST_STACKING",
    "_NET_DESKTOP_VIEWPORT",
    "_NET_DESKTOP_GEOMETRY",
    "_NET_NUMBER_OF_DESKTOPS",
    "_NET_DESKTOP_NAMES",
    "_NET_WORKAREA",
    "_NET_ACTIVE_WINDOW",
    "_NET_CURRENT_DESKTOP",
    "_NET_SHOWING_DESKTOP",

    "WM_NAME", "_NET_WM_NAME",
    "WM_ICON_NAME", "_NET_WM_ICON_NAME",
    "WM_ICON_SIZE",
    "WM_CLASS",
    "WM_PROTOCOLS",
    "_NET_WM_PID",
    "WM_CLIENT_MACHINE",
    "WM_STATE",

    "_NET_WM_FULLSCREEN_MONITORS",

    "_NET_WM_ALLOWED_ACTIONS",
    "_NET_WM_ACTION_CLOSE",
    "_NET_WM_ACTION_FULLSCREEN",

    # We don't actually use _NET_WM_USER_TIME at all (yet), but it is
    # important to say we support the _NET_WM_USER_TIME_WINDOW property,
    # because this tells applications that they do not need to constantly
    # ping any pagers etc. that might be running -- see EWMH for details.
    # (Though it's not clear that any applications actually take advantage
    # of this yet.)
    "_NET_WM_USER_TIME",
    "_NET_WM_USER_TIME_WINDOW",
    # Not fully:
    "WM_HINTS",
    "WM_NORMAL_HINTS",
    "WM_TRANSIENT_FOR",
    "_NET_WM_STRUT",
    "_NET_WM_STRUT_PARTIAL"
    "_NET_WM_ICON",

    "_NET_CLOSE_WINDOW",

    # These aren't supported in any particularly meaningful way, but hey.
    "_NET_WM_WINDOW_TYPE",
    "_NET_WM_WINDOW_TYPE_NORMAL",
    "_NET_WM_WINDOW_TYPE_DESKTOP",
    "_NET_WM_WINDOW_TYPE_DOCK",
    "_NET_WM_WINDOW_TYPE_TOOLBAR",
    "_NET_WM_WINDOW_TYPE_MENU",
    "_NET_WM_WINDOW_TYPE_UTILITY",
    "_NET_WM_WINDOW_TYPE_SPLASH",
    "_NET_WM_WINDOW_TYPE_DIALOG",
    "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
    "_NET_WM_WINDOW_TYPE_POPUP_MENU",
    "_NET_WM_WINDOW_TYPE_TOOLTIP",
    "_NET_WM_WINDOW_TYPE_NOTIFICATION",
    "_NET_WM_WINDOW_TYPE_COMBO",
    # "_NET_WM_WINDOW_TYPE_DND",

    "_NET_WM_STATE",
    "_NET_WM_STATE_DEMANDS_ATTENTION",
    "_NET_WM_STATE_MODAL",
    # More states to support:
    "_NET_WM_STATE_STICKY",
    "_NET_WM_STATE_MAXIMIZED_VERT",
    "_NET_WM_STATE_MAXIMIZED_HORZ",
    "_NET_WM_STATE_SHADED",
    "_NET_WM_STATE_SKIP_TASKBAR",
    "_NET_WM_STATE_SKIP_PAGER",
    "_NET_WM_STATE_HIDDEN",
    "_NET_WM_STATE_FULLSCREEN",
    "_NET_WM_STATE_ABOVE",
    "_NET_WM_STATE_BELOW",
    "_NET_WM_STATE_FOCUSED",

    "_NET_WM_DESKTOP",

    "_NET_WM_MOVERESIZE",
    "_NET_MOVERESIZE_WINDOW",

    "_MOTIF_WM_HINTS",
    "_MOTIF_WM_INFO",

    "_NET_REQUEST_FRAME_EXTENTS",
    "_NET_RESTACK_WINDOW",

    "_NET_WM_OPAQUE_REGION",
]
FRAME_EXTENTS = envbool("XPRA_FRAME_EXTENTS", True)
if FRAME_EXTENTS:
    DEFAULT_NET_SUPPORTED.append("_NET_FRAME_EXTENTS")

NO_NET_SUPPORTED = os.environ.get("XPRA_NO_NET_SUPPORTED", "").split(",")

NET_SUPPORTED = [x for x in DEFAULT_NET_SUPPORTED if x not in NO_NET_SUPPORTED]


# Just to make it easier to pass around and have a helpful debug logging.
# Really, just a python objects where we can stick random bags of attributes.
class X11Event:
    def __init__(self, etype: int, name: str, send_event: bool, serial: int, delivered_to: int):
        self.event_type = etype
        self.name = name
        self.send_event = send_event
        self.serial = serial
        self.delivered_to = delivered_to

    def __repr__(self):
        d = {}
        for k, v in self.__dict__.items():
            if k in ("name", "display", "type"):
                continue
            if k in ("serial", "window", "delivered_to", "above", "below", "damage", "time") and isinstance(v, int):
                d[k] = hex(v)
            elif k == "send_event" and v is False:
                continue
            else:
                fn = REPR_FUNCTIONS.get(type(v), str)
                d[k] = fn(v)
        return f"<X11:{self.name} {d!r}>"


def get_wm_name() -> str:
    from xpra.x11.xroot_props import root_get
    wm_check = root_get("_NET_SUPPORTING_WM_CHECK", "window")
    log("_NET_SUPPORTING_WM_CHECK window=%#x", wm_check)
    if not wm_check:
        return ""
    from xpra.x11.prop import prop_get
    return prop_get(wm_check, "_NET_WM_NAME", "utf8", ignore_errors=True) or ""


def get_vrefresh() -> int:
    v = -1
    try:
        from xpra.x11.bindings.randr import RandRBindings
        randr = RandRBindings()
        if randr.has_randr():
            v = randr.get_vrefresh()
    except Exception as e:
        log("get_vrefresh()", exc_info=True)
        log.error("Error querying the display vertical refresh rate:")
        log.estr(e)
    log("get_vrefresh()=%s", v)
    return v


def send_client_message(xid, message_type: str, *values) -> None:
    from xpra.x11.bindings.core import constants, get_root_xid
    from xpra.x11.bindings.window import X11WindowBindings
    X11Window = X11WindowBindings()
    SubstructureNotifyMask = constants["SubstructureNotifyMask"]
    SubstructureRedirectMask = constants["SubstructureRedirectMask"]
    event_mask = SubstructureNotifyMask | SubstructureRedirectMask
    root_xid = get_root_xid()
    log("sendClientMessage(%#x, %#x, %s, %#x, %r, %r)", root_xid, xid, False, event_mask, message_type, values)
    X11Window.sendClientMessage(root_xid, xid, False, event_mask, message_type, *values)


device_bell: bool | None = None


def system_bell(xid: int, device: int, percent: int, _pitch, _duration: int, bell_class, bell_id, bell_name: str) -> bool:
    global device_bell
    if device_bell is False:
        # failed already
        return False
    if device_bell is None:
        # try to load it:
        try:
            from xpra.x11.bindings.keyboard import X11KeyboardBindings
            device_bell = X11KeyboardBindings().device_bell
        except ImportError:
            log("x11_bell()", exc_info=True)
            log.warn("Warning: cannot use X11 bell device without the X11 bindings")
            return False
    device_bell(xid, device, bell_class, bell_id, percent, bell_name)
    return True


def get_xsettings():
    from xpra.x11.bindings.window import X11WindowBindings  # @UnresolvedImport
    X11Window = X11WindowBindings()
    selection = "_XSETTINGS_S0"
    owner = X11Window.XGetSelectionOwner(selection)
    if not owner:
        return None
    XSETTINGS = "_XSETTINGS_SETTINGS"
    data = X11Window.XGetWindowProperty(owner, XSETTINGS, XSETTINGS)
    if not data:
        return None
    from xpra.x11.subsystem.xsettings_prop import bytes_to_xsettings
    return bytes_to_xsettings(data)


def xsettings_to_dict(v) -> dict[str, tuple[int, Any]]:
    d: dict[str, tuple[int, Any]] = {}
    if v:
        _, values = v
        for setting_type, prop_name, value, _ in values:
            d[bytestostr(prop_name)] = (setting_type, value)
    return d


def get_randr_dpi() -> tuple[int, int]:
    from xpra.x11.bindings.randr import RandRBindings  # @UnresolvedImport
    randr_bindings = RandRBindings()
    if randr_bindings and randr_bindings.has_randr():
        wmm, hmm = randr_bindings.get_screen_size_mm()
        if wmm > 0 and hmm > 0:
            w, h = randr_bindings.get_screen_size()
            dpix = round(w * 25.4 / wmm)
            dpiy = round(h * 25.4 / hmm)
            log("xdpi=%s, ydpi=%s - size-mm=%ix%i, size=%ix%i", dpix, dpiy, wmm, hmm, w, h)
            if w > 0 and h > 0:
                return dpix, dpiy
    return -1, -1


def get_default_cursor_size() -> tuple[int, int]:
    from xpra.x11.xroot_props import get_xresources
    d = get_xresources()
    try:
        size = int(d.get("Xcursor.size", 0))
    except ValueError:
        size = 0
    if not size:
        try:
            from xpra.x11.bindings.cursor import X11CursorBindings
            cursor = X11CursorBindings()
            size = cursor.get_default_cursor_size()
        except ImportError:
            log("get_default_cursor_size() no x11 cursor bindings")
    return size, size
