# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.str_fn import csv
from xpra.x11.error import xswallow

from xpra.x11.bindings.window import X11WindowBindings


def get_wintitle(xid: int) -> str:
    X11Window = X11WindowBindings()
    with xswallow:
        data = X11Window.XGetWindowProperty(xid, "WM_NAME", "STRING")
        if data:
            return data.decode("latin1")
    with xswallow:
        data = X11Window.XGetWindowProperty(xid, "_NET_WM_NAME", "UTF8_STRING")
        if data:
            return data.decode("utf8")
    return ""


def get_wininfo(xid: int) -> str:
    wininfo = [f"xid={xid:x}"]
    try:
        from xpra.x11.bindings.res import ResBindings
        XRes = ResBindings()
    except ImportError:
        pass
    else:
        if XRes.check_xres():
            with xswallow:
                pid = XRes.get_pid(xid)
                if pid:
                    wininfo.append(f"pid={pid}")
    title = get_wintitle(xid)
    if title:
        wininfo.insert(0, repr(title))
        return csv(wininfo)
    while xid:
        title = get_wintitle(xid)
        if title:
            wininfo.append(f"child of {title!r}")
            return csv(wininfo)
        with xswallow:
            X11Window = X11WindowBindings()
            xid = X11Window.getParent(xid)
    return csv(wininfo)
