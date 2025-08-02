# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.env import envbool
from xpra.x11.error import xsync, xlog
from xpra.x11.prop import prop_get
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.bindings.window import X11WindowBindings
from xpra.log import Logger

log = Logger("x11", "window")

WM_S0 = "WM_S0"
_NEW_WM_CM_S0 = "_NEW_WM_CM_S0"

FORCE_REPLACE_WM = envbool("XPRA_FORCE_REPLACE_WM", False)


def get_ewmh_xid() -> int:
    with xlog:
        X11Window = X11WindowBindings()
        root_xid = get_root_xid()
        ewmh_xid = prop_get(root_xid, "_NET_SUPPORTING_WM_CHECK", "window", ignore_errors=True)
        if ewmh_xid:
            try:
                with xsync:
                    if X11Window.getGeometry(ewmh_xid):
                        return ewmh_xid
            except Exception as e:
                log(f"getGeometry({ewmh_xid:x}) {e}")
    return 0


def get_wm_info() -> dict[str, Any]:
    from xpra.x11.bindings.display_source import get_display_name
    with xsync:
        X11Window = X11WindowBindings()
        root_xid = get_root_xid()
        info = {
            "root": root_xid,
            "display": get_display_name(),
        }
        s0 = X11Window.XGetSelectionOwner(WM_S0)
        if s0:
            info["WM_S0"] = s0
        s0 = X11Window.XGetSelectionOwner(_NEW_WM_CM_S0)
        if s0:
            info["_NEW_WM_CM_S0"] = s0
    ewmh_xid = get_ewmh_xid()
    if ewmh_xid:
        info["_NET_SUPPORTING_WM_CHECK"] = ewmh_xid
        with xlog:
            wm_name = prop_get(ewmh_xid, "_NET_WM_NAME", "utf8", ignore_errors=True)
            if not wm_name:
                wm_name = prop_get(root_xid, "_NET_WM_NAME", "utf8", ignore_errors=True)
            if wm_name:
                info["wmname"] = wm_name
    for name, prop_name, prop_type in (
            ("xpra-server-pid", "XPRA_SERVER_PID", "u32"),
            ("xpra-vfb-pid", "XPRA_XVFB_PID", "u32"),
            ("xpra-server-version", "XPRA_SERVER", "latin1"),
            ("xpra-server-mode", "XPRA_SERVER_MODE", "latin1"),
            ("dbus-address", "DBUS_SESSION_BUS_ADDRESS", "latin1"),
            ("dbus-pid", "DBUS_SESSION_BUS_PID", "u32"),
            ("dbus-window", "DBUS_SESSION_BUS_WINDOW_ID", "u32"),
    ):
        v = prop_get(root_xid, prop_name, prop_type, ignore_errors=True, raise_xerrors=False)
        if v is not None:
            info[name] = v
    log("get_wm_info()=%s", info)
    return info


def wm_check(upgrading=False) -> bool:
    info = get_wm_info()
    display_name = info.get("display", "")
    name = info.get("wmname")
    wm_so = info.get("WM_S0")
    cwm_so = info.get("_NEW_WM_CM_S0")
    ewmh_xid = info.get("_NET_SUPPORTING_WM_CHECK", 0)
    xpra_name = name and name.lower().startswith("xpra")
    if not upgrading and not (ewmh_xid or wm_so or cwm_so):
        log("no window manager on %s", display_name)
        return True
    if upgrading and xpra_name:
        log.info("found previous Xpra instance")
        return True
    if not name:
        log.warn("Warning: no window manager found")
        log.warn(" on display %s using EWMH window %#x", display_name, ewmh_xid)
    else:
        log.warn("Warning: found an existing window manager")
        log.warn(" on display %s using EWMH window %#x: '%s'", display_name, ewmh_xid, name)
    if not wm_so and not cwm_so:
        if xpra_name:
            log.info(" found remnants of a previous Xpra instance")
            return True
        if FORCE_REPLACE_WM:
            log.warn(" XPRA_FORCE_REPLACE_WM is set, replacing it forcibly")
            return True
        log.warn(" it does not own the selection '%s' or '%s'", WM_S0, _NEW_WM_CM_S0)
        log.warn(" so we cannot take over and make it exit")
        log.warn(" please stop %s so you can run xpra on this display",
                 name or "the existing window manager")
        log.warn(" if you are certain that the window manager is already gone,")
        log.warn(" you may set XPRA_FORCE_REPLACE_WM=1 to force xpra to continue")
        log.warn(" at your own risk")
        return False
    if upgrading and not FORCE_REPLACE_WM and name:
        log.error("Error: %r is managing this display", name)
        log.error(" you may set XPRA_FORCE_REPLACE_WM=1 to force xpra to continue")
        log.error(" at your own risk")
        return False
    return True


def main() -> None:
    # pylint: disable=import-outside-toplevel
    from xpra.x11.bindings.display_source import init_display_source
    init_display_source()
    wm_check()


if __name__ == "__main__":  # pragma: no cover
    main()
