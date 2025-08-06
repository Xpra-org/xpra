# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from typing import Any, cast
from collections.abc import Callable, Sequence

from xpra.util.env import envbool
from xpra.util.str_fn import Ellipsizer, bytestostr, hexstr
from xpra.log import Logger

log = Logger("x11")


class Unmanageable(Exception):
    pass


REPR_FUNCTIONS: dict[type, Callable] = {}


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
    def __init__(self, name: str):
        self.name: str = name

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


# we duplicate some of the code found in xpra.x11.gtk.prop ...
# which is still better than having dependencies on that GTK here
def get_X11_window_property(xid: int, name: str, req_type: str):
    try:
        from xpra.x11.bindings.window import X11WindowBindings, PropertyError
        try:
            prop = X11WindowBindings().XGetWindowProperty(xid, name, req_type)
            log("get_X11_window_property(%#x, %s, %s)=%s, len=%s", xid, name, req_type, type(prop), len(prop or ()))
            return prop
        except PropertyError as e:
            log("get_X11_window_property(%#x, %s, %s): %s", xid, name, req_type, e)
    except Exception as e:
        log.warn(f"Warning: failed to get X11 window property {name!r} on window {xid:x}: {e}")
        log("get_X11_window_property%s", (xid, name, req_type), exc_info=True)
    return None


def get_X11_root_property(name: str, req_type: str):
    try:
        from xpra.x11.bindings.core import get_root_xid
        return get_X11_window_property(get_root_xid(), name, req_type)
    except Exception as e:
        log("get_X11_root_property(%s, %s)", name, req_type, exc_info=True)
        log.warn(f"Warning: failed to get X11 root property {name!r}")
        log.warn(" %s", e)
    return None


def get_wm_name() -> str:
    try:
        wm_check = get_X11_root_property("_NET_SUPPORTING_WM_CHECK", "WINDOW")
        if wm_check:
            xid = struct.unpack(b"@L", wm_check)[0]
            log("_NET_SUPPORTING_WM_CHECK window=%#x", xid)
            wm_name = get_X11_window_property(xid, "_NET_WM_NAME", "UTF8_STRING")
            log("_NET_WM_NAME=%s", wm_name)
            if wm_name:
                return wm_name.decode("utf8")
    except Exception as e:
        log("get_wm_name()", exc_info=True)
        log.error("Error accessing window manager information:")
        log.estr(e)
    return ""


def get_icc_data() -> dict[str, Any]:
    icc: dict[str, Any] = {}
    try:
        data = get_X11_root_property("_ICC_PROFILE", "CARDINAL")
        if data:
            log("_ICC_PROFILE=%s (%s)", type(data), len(data))
            version = get_X11_root_property("_ICC_PROFILE_IN_X_VERSION", "CARDINAL")
            log("get_icc_info() found _ICC_PROFILE_IN_X_VERSION=%s, _ICC_PROFILE=%s",
                hexstr(version or ""), Ellipsizer(hexstr(data)))
            icc |= {
                "source": "_ICC_PROFILE",
                "data": data,
            }
            if version:
                try:
                    version = ord(version)
                except TypeError:
                    pass
                icc["version"] = version
    except Exception as e:
        log.error("Error: cannot access `_ICC_PROFILE` X11 window property")
        log.estr(e)
        log("get_icc_info()", exc_info=True)
    log("get_x11_icc_data()=%s", Ellipsizer(icc))
    return icc


def get_current_desktop() -> int:
    v = -1
    d = None
    try:
        d = get_X11_root_property("_NET_CURRENT_DESKTOP", "CARDINAL")
        if d:
            v = struct.unpack(b"@L", d)[0]
    except Exception as e:
        log("get_current_desktop()", exc_info=True)
        log.error("Error: accessing `_NET_CURRENT_DESKTOP`:")
        log.estr(e)
    log("get_current_desktop() %s=%s", hexstr(d or ""), v)
    return v


def get_number_of_desktops() -> int:
    v = 0
    d = None
    try:
        d = get_X11_root_property("_NET_NUMBER_OF_DESKTOPS", "CARDINAL")
        if d:
            v = struct.unpack(b"@L", d)[0]
    except Exception as e:
        log("get_number_of_desktops()", exc_info=True)
        log.error("Error: accessing `_NET_NUMBER_OF_DESKTOPS`:")
        log.estr(e)
    v = max(1, v)
    log("get_number_of_desktops() %s=%s", hexstr(d or ""), v)
    return v


def get_workarea() -> tuple[int, int, int, int] | None:
    try:
        d = get_current_desktop()
        if d < 0:
            return None
        workarea = get_X11_root_property("_NET_WORKAREA", "CARDINAL")
        if not workarea:
            return None
        log("get_workarea() _NET_WORKAREA=%s (%s), len=%s",
            Ellipsizer(workarea), type(workarea), len(workarea))
        # workarea comes as a list of 4 CARDINAL dimensions (x,y,w,h), one for each desktop
        sizeof_long = struct.calcsize(b"@L")
        if len(workarea) < (d+1)*4*sizeof_long:
            log.warn(f"Warning: invalid `_NET_WORKAREA` value length: {workarea!r}")
        else:
            cur_workarea = workarea[d*4*sizeof_long:(d+1)*4*sizeof_long]
            v = cast(tuple[int, int, int, int], struct.unpack(b"@LLLL", cur_workarea))
            log("get_workarea() %s=%s", hexstr(cur_workarea), v)
            return v
    except Exception as e:
        log("get_workarea()", exc_info=True)
        log.error("Error: querying the x11 workarea:")
        log.estr(e)
    return None


def get_desktop_names() -> Sequence[str]:
    ret: Sequence[str] = ("Main", )
    d = None
    try:
        d = get_X11_root_property("_NET_DESKTOP_NAMES", "UTF8_STRING")
        if d:
            d = d.split(b"\0")
            if len(d) > 1 and d[-1] == b"":
                d = d[:-1]
            ret = tuple(x.decode("utf8") for x in d)
    except Exception as e:
        log.error("Error querying `_NET_DESKTOP_NAMES`:")
        log.estr(e)
    log("get_desktop_names() %s=%s", hexstr(d or ""), ret)
    return ret


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


def send_client_message(window, message_type: str, *values) -> None:
    try:
        from xpra.x11.bindings.core import get_root_xid
        from xpra.x11.bindings.window import constants, X11WindowBindings  # @UnresolvedImport
        X11Window = X11WindowBindings()
        root_xid = get_root_xid()
        if window:
            xid = window.get_xid()
        else:
            xid = root_xid
        SubstructureNotifyMask = constants["SubstructureNotifyMask"]
        SubstructureRedirectMask = constants["SubstructureRedirectMask"]
        event_mask = SubstructureNotifyMask | SubstructureRedirectMask
        X11Window.sendClientMessage(root_xid, xid, False, event_mask, message_type, *values)
    except Exception as e:
        log.warn(f"Warning: failed to send client message {message_type!r} with values={values}: {e}")


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
    from xpra.x11.xsettings_prop import bytes_to_xsettings
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
            return dpix, dpiy
    return -1, -1


def get_xresources() -> dict[str, str] | None:
    try:
        value = get_X11_root_property("RESOURCE_MANAGER", "STRING")
        log(f"RESOURCE_MANAGER={value}")
        if value is None:
            return None
        # parse the resources into a dict:
        values: dict[str, str] = {}
        options = bytestostr(value).split("\n")
        for option in options:
            if not option:
                continue
            parts = option.split(":\t", 1)
            if len(parts) != 2:
                log(f"skipped invalid option: {option!r}")
                continue
            values[parts[0]] = parts[1]
        return values
    except Exception as e:
        log(f"_get_xresources error: {e!r}")
    return None


def get_cursor_size() -> int:
    d = get_xresources() or {}
    try:
        return int(d.get("Xcursor.size", 0))
    except ValueError:
        return -1
