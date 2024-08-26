# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def window_name(xid: int) -> str:
    from xpra.x11.gtk.prop import prop_get
    return prop_get(xid, "_NET_WM_NAME", "utf8", True) or "unknown"


def window_info(xid: int) -> str:
    from xpra.x11.gtk.prop import prop_get
    net_wm_name = prop_get(xid, "_NET_WM_NAME", "utf8", True)
    from xpra.x11.bindings.window import X11WindowBindings
    X11Window = X11WindowBindings()
    from xpra.gtk.error import xlog
    geom = None     # @UnusedVariable
    mapped = False  # @UnusedVariable
    with xlog:
        isor = X11Window.is_override_redirect(xid)
        geom = X11Window.getGeometry(xid)
        mapped = X11Window.is_mapped(xid)
    info = [
        "mapped" if mapped else "unmapped",
        "override redirect window" if isor else "window"
    ]
    if net_wm_name:
        info.append(net_wm_name)
    else:
        info.append(hex(xid))
    if geom:
        info.append(str(geom[:4]))
    return " ".join(info)


def dump_windows() -> None:
    from xpra.log import Logger
    log = Logger("x11", "window")
    try:
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.gtk.error import xlog
    except ImportError:
        pass
    else:
        with xlog:
            X11Window = X11WindowBindings()
            xid = X11Window.get_root_xid()
            log(f"root window: {xid:x}")
            children = X11Window.get_children(xid)
            log("%s windows" % len(xid))
            for cxid in children:
                log("found window: %s", window_info(cxid))
