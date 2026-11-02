# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The size of the window manager's decorations (aka "frame extents"):
from the platform code if it can tell us,
or by asking the X11 window manager via `_NET_REQUEST_FRAME_EXTENTS`.
"""

from typing import Any

from xpra.os_util import gi_import
from xpra.util.env import first_time
from xpra.client.gtk3.window.common import use_x11_bindings
from xpra.platform.gui import get_window_frame_sizes as get_platform_frame_sizes, get_window_frame_size, get_wm_name
from xpra.log import Logger

Gtk = gi_import("Gtk")

log = Logger("gtk", "client", "frame")

# a hidden window, used for querying the frame size before we have any windows:
frame_request_window = None


def x11_array_get():
    if not use_x11_bindings():
        return None
    try:
        from xpra.x11.prop import array_get
    except (ImportError, RuntimeError):
        return None
    return array_get


def send_request_frame_extents(xid: int) -> None:
    from xpra.x11.error import xsync
    from xpra.x11.bindings.send_wm import send_wm_request_frame_extents
    from xpra.x11.bindings.core import get_root_xid
    with xsync:
        send_wm_request_frame_extents(get_root_xid(), xid)


def setup_frame_request_window() -> None:
    """ X11 only: ask the window manager for the frame extents of a hidden window """
    global frame_request_window
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title("Xpra-FRAME_EXTENTS")
    window.realize()
    xid = window.get_window().get_xid()
    log("setup_frame_request_window() window=%#x", xid)
    frame_request_window = window
    send_request_frame_extents(xid)


def request_frame_extents(window) -> None:
    """ X11 only: ask the window manager to set `_NET_FRAME_EXTENTS` on this window """
    xid = window.get_window().get_xid()
    log(f"request_frame_extents({window}) xid={xid:x}")
    send_request_frame_extents(xid)


def get_frame_extents(window) -> dict[str, Any]:
    # try native platform code first:
    x, y = window.get_position()
    w, h = window.get_size()
    v = get_window_frame_size(x, y, w, h)  # pylint: disable=assignment-from-none
    log(f"get_window_frame_size{(x, y, w, h)}={v}")
    if v:
        # (OSX does give us these values via Quartz API)
        return v
    array_get = x11_array_get()
    if not array_get:
        # nothing more we can do!
        return {}
    gdkwin = window.get_window()
    assert gdkwin
    v = array_get(gdkwin.get_xid(), "_NET_FRAME_EXTENTS", "u32", ignore_errors=False)
    log(f"get_frame_extents({window.get_title()})={v}")
    if not v:
        return {}
    return {"frame": v}


def get_window_frame_sizes() -> dict[str, Any]:
    """ the frame sizes for all windows, using the hidden frame request window if we have one """
    wfs = get_platform_frame_sizes()
    if frame_request_window:
        extents = get_frame_extents(frame_request_window)
        if v := extents.get("frame", ()):
            try:
                wm_name = get_wm_name()  # pylint: disable=assignment-from-none
            except Exception:
                wm_name = ""
            try:
                if len(v) == 8:
                    if first_time("invalid-frame-extents"):
                        log.warn(f"Warning: invalid frame extents value {v!r}")
                        log.warn(" expected 8 elements but found %s", len(v))
                        if wm_name:
                            log.warn(f" this is probably a bug in {wm_name!r}")
                        log.warn(f" using {v[4:]} instead")
                    v = v[4:]
                if max(abs(value) for value in v) > 256:
                    if first_time("invalid-frame-extents"):
                        log.warn(f"Warning: invalid frame extents value {v!r}")
                else:
                    l, r, t, b = v
                    wfs["frame"] = (l, r, t, b)
                    wfs["offset"] = (l, t)
            except Exception as e:
                log.warn(f"Warning: invalid frame extents value {v!r}")
                log.warn(f" {e}")
                if wm_name:
                    log.warn(f" this is probably a bug in {wm_name!r}")
    log(f"get_window_frame_sizes()={wfs}")
    return wfs
