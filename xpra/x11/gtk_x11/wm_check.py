# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import envbool
from xpra.gtk_common.error import xsync
from xpra.x11.gtk_x11.prop import prop_get, raw_prop_get
from xpra.x11.bindings.window_bindings import X11WindowBindings #@UnresolvedImport
from xpra.log import Logger

log = Logger("x11", "window")

WM_S0 = "WM_S0"
_NEW_WM_CM_S0 = "_NEW_WM_CM_S0"

FORCE_REPLACE_WM = envbool("XPRA_FORCE_REPLACE_WM", False)
def get_wm_info():
    with xsync:
        from gi.repository import Gdk  #pylint: disable=import-outside-toplevel
        display = Gdk.Display.get_default()
        X11Window = X11WindowBindings()
        screen = display.get_default_screen()
        root = screen.get_root_window()
        info = {
            "display"   : display.get_name(),
            "root"      : root.get_xid(),
            "WM_S0"     : X11Window.XGetSelectionOwner(WM_S0) or 0,
            "_NEW_WM_CM_S0" : X11Window.XGetSelectionOwner(_NEW_WM_CM_S0) or 0,
            }
        ewmh_xid = raw_prop_get(root, "_NET_SUPPORTING_WM_CHECK", "window", ignore_errors=False, raise_xerrors=False)
        if ewmh_xid:
            ewmh_wm = prop_get(root, "_NET_SUPPORTING_WM_CHECK", "window", ignore_errors=True, raise_xerrors=False)
            if ewmh_wm:
                info["_NET_SUPPORTING_WM_CHECK"] = ewmh_wm.get_xid()
                info["wmname"] = prop_get(ewmh_wm, "_NET_WM_NAME", "utf8", ignore_errors=True, raise_xerrors=False) or ""
            else:
                info["wmname"] = prop_get(root, "_NET_WM_NAME", "utf8", ignore_errors=True, raise_xerrors=False) or ""
        for name, prop_name, prop_type in (
            ("xpra-server-pid",     "XPRA_SERVER_PID",              "u32"),
            ("xpra-vfb-pid",        "XPRA_XVFB_PID",                "u32"),
            ("xpra-server-version", "XPRA_SERVER",                  "latin1"),
            ("xpra-server-mode",    "XPRA_SERVER_MODE",             "latin1"),
            ("dbus-address",        "DBUS_SESSION_BUS_ADDRESS",     "latin1"),
            ("dbus-pid",            "DBUS_SESSION_BUS_PID",         "u32"),
            ("dbus-window",         "DBUS_SESSION_BUS_WINDOW_ID",   "u32"),
            ):
            v = prop_get(root, prop_name, prop_type, ignore_errors=True, raise_xerrors=False)
            if v:
                info[name] = v
    log("get_wm_info()=%s", info)
    return info

def wm_check(wm_name="xpra", upgrading=False):
    info = get_wm_info()
    display_name = info.get("display")
    name = info.get("wmname")
    wm_so = info.get("WM_S0")
    cwm_so = info.get("_NEW_WM_CM_S0")
    ewmh_xid = info.get("_NET_SUPPORTING_WM_CHECK", 0)
    if not upgrading and not (ewmh_xid or wm_so or cwm_so):
        log("no window manager on %s", display_name)
        return True
    found_name = False
    if upgrading and name and name==wm_name:
        log.info("found previous Xpra instance")
        return True
    if not name:
        log.warn("Warning: no window manager found")
        log.warn(" on display %s using EWMH window %#x", display_name, ewmh_xid)
    else:
        log.warn("Warning: found an existing window manager")
        log.warn(" on display %s using EWMH window %#x: '%s'", display_name, ewmh_xid, name)
    if not wm_so and not cwm_so:
        if name and name.lower().startswith("xpra"):
            log.info("found remnants of a previous Xpra instance")
            return True
        if FORCE_REPLACE_WM:
            log.warn("XPRA_FORCE_REPLACE_WM is set, replacing it forcibly")
        else:
            log.error("it does not own the selection '%s' or '%s'", WM_S0, _NEW_WM_CM_S0)
            log.error("so we cannot take over and make it exit")
            log.error("please stop %s so you can run xpra on this display",
                      name or "the existing window manager")
            log.warn("if you are certain that the window manager is already gone,")
            log.warn(" you may set XPRA_FORCE_REPLACE_WM=1 to force xpra to continue")
            log.warn(" at your own risk")
            return False
    if upgrading and not found_name and not FORCE_REPLACE_WM:
        log.error("Error: xpra server not found")
        return False
    return True


def main():
    from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
    init_gdk_display_source()
    wm_check()


if __name__ == "__main__":  # pragma: no cover
    main()
