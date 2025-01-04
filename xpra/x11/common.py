# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from typing import Any, cast
from collections.abc import Callable, Sequence

from xpra.util.str_fn import Ellipsizer, bytestostr, hexstr
from xpra.log import Logger
log = Logger("x11")


class Unmanageable(Exception):
    pass


REPR_FUNCTIONS: dict[type, Callable] = {}


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
        from xpra.x11.bindings.window import X11WindowBindings
        return get_X11_window_property(X11WindowBindings().get_root_xid(), name, req_type)
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
        from xpra.x11.bindings.window import constants, X11WindowBindings  # @UnresolvedImport
        X11Window = X11WindowBindings()
        root_xid = X11Window.get_root_xid()
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


device_bell = None


def system_bell(xid: int, device, percent: int, _pitch, _duration: int, bell_class, bell_id, bell_name: str) -> bool:
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
