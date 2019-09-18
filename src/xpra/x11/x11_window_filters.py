# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2015-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
from xpra.os_util import strtobytes
from xpra.gtk_common.error import xsync
from xpra.x11.gtk_x11.prop import prop_get, get_python_type
from xpra.x11.bindings.window_bindings import X11WindowBindings     #@UnresolvedImport

window_bindings = X11WindowBindings()
log = Logger("x11", "filters")


def get_x11_window_value(prop, window):
    try:
        with xsync:
            xid = window.get_xid()
            x11type = window_bindings.GetWindowPropertyType(xid, prop)[0]
    except Exception:
        log("get_x11_window_value(%s, %s)", prop, window, exc_info=True)
        x11type = None
    if x11type:
        ptype = get_python_type(x11type)
        #log("%s: %s (%s)", filter_object.property_name, x11type, ptype)
        assert ptype, "type '%s' is not handled!" % x11type
        v = prop_get(window, prop, ptype)
        log("prop_get(%s, %s, %s)=%s", window, prop, ptype, v)
        if v and isinstance(v, str):
            v = strtobytes(v).replace("\0", "")
    else:
        v = None
    log("%s=%s (type=%s)", prop, v, x11type)
    return v

def get_window_value(filter_object, gdkwin):
    return get_x11_window_value(filter_object.property_name, gdkwin)

def get_window(filter_object, window):
    gdkwin = window.get_property("client-window")
    p = gdkwin
    log("get_window%s gdkwin=%s, recurse=%s", (filter_object, window), gdkwin, filter_object.recurse)
    while filter_object.recurse and p:
        gdkwin = p
        p = None
        try:
            prop = "WM_TRANSIENT_FOR"
            p = prop_get(gdkwin, prop, "window", ignore_errors=True)
            log("prop_get(%s, %s)=%s", gdkwin, prop, p)
        except Exception:
            log("prop_get(%s, %s)", gdkwin, prop, exc_info=True)
            break
    return gdkwin

def init_x11_window_filters():
    from xpra.server.window import filters
    original_get_window_filter = filters.get_window_filter

    def get_x11_window_filter(object_name, property_name, operator, value):
        oname = object_name.lower()
        wf = original_get_window_filter(oname.replace("x11:", ""), property_name, operator, value)
        if oname.startswith("x11:"):
            #same filter but use X11 properties:
            import types
            wf.get_window = types.MethodType(get_window, wf)
            wf.get_window_value = types.MethodType(get_window_value, wf)
            log("patched methods: %s, %s", wf.get_window, wf.get_window_value)
        log("x11 get_window_filter%s=%s", (object_name, property_name, operator, value), wf)
        return wf

    filters.get_window_filter = get_x11_window_filter
    log("init_x11_window_filters() filters.get_window_filter=%s", filters.get_window_filter)
