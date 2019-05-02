# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def window_name(window):
    from xpra.x11.gtk_x11.prop import prop_get
    return prop_get(window, "_NET_WM_NAME", "utf8", True) or "unknown"

def window_info(window):
    from xpra.x11.gtk_x11.prop import prop_get
    net_wm_name = prop_get(window, "_NET_WM_NAME", "utf8", True)
    return "%s %s visible=%s" % (net_wm_name, window.get_geometry(), window.is_visible())


def dump_windows():
    from xpra.log import Logger
    log = Logger("x11", "window")
    from xpra.gtk_common.gtk_util import get_default_root_window
    root = get_default_root_window()
    log("root window: %s" % root)
    try:
        from xpra.x11.gtk_x11.gdk_bindings import get_children #@UnresolvedImport
    except ImportError:
        pass
    else:
        children = get_children(root)
        log("%s windows" % len(children))
        for window in get_children(root):
            log("found window: %s", window_info(window))
