# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
from xpra.util.str_fn import strtobytes
from xpra.x11.error import xsync
from xpra.x11.prop import prop_get, get_python_type
from xpra.x11.bindings.window import X11WindowBindings

window_bindings = X11WindowBindings()
log = Logger("x11", "filters")


def get_x11_window_value(prop, window):
    try:
        with xsync:
            xid = window.get_xid()
            x11type = window_bindings.GetWindowPropertyType(xid, prop)[0]
    except Exception:
        log("get_x11_window_value(%s, %s)", prop, window, exc_info=True)
        x11type = ""
    if x11type:
        ptype = get_python_type(x11type)
        # log("%s: %s (%s)", filter_object.property_name, x11type, ptype)
        assert ptype, "type '%s' is not handled!" % x11type
        v = prop_get(window.get_xid(), prop, ptype)
        log("prop_get(%s, %s, %s)=%s", window, prop, ptype, v)
        if v and isinstance(v, str):
            v = strtobytes(v).replace(b"\0", b"")
    else:
        v = None
    log("%s=%s (type=%s)", prop, v, x11type)
    return v


def get_window_value(filter_object, gdkwin):
    return get_x11_window_value(filter_object.property_name, gdkwin)


def get_window(filter_object, window):
    xid = window.get_property("xid")
    p = xid
    log(f"get_window({filter_object}, {window}) xid={xid:x}, recurse={filter_object.recurse}")
    WM_TRANSIENT_FOR = "WM_TRANSIENT_FOR"
    while filter_object.recurse and p:
        try:
            xid = prop_get(p, WM_TRANSIENT_FOR, "window", ignore_errors=True)
            log(f"prop_get({p:x}, {WM_TRANSIENT_FOR})={xid}")
            if not xid:
                return p
            p = xid
        except Exception:
            log(f"prop_get({p:x}, {WM_TRANSIENT_FOR})", exc_info=True)
            break
    return p


def init_x11_window_filters() -> None:
    from xpra.server.window import filters
    original_get_window_filter = filters.get_window_filter

    def get_x11_window_filter(object_name, property_name, operator, value):
        oname = object_name.lower()
        wf = original_get_window_filter(oname.replace("x11:", ""), property_name, operator, value)
        if oname.startswith("x11:"):
            # same filter but use X11 properties:
            import types
            wf.get_window = types.MethodType(get_window, wf)
            wf.get_window_value = types.MethodType(get_window_value, wf)
            log("patched methods: %s, %s", wf.get_window, wf.get_window_value)
        log("x11 get_window_filter%s=%s", (object_name, property_name, operator, value), wf)
        return wf

    filters.get_window_filter = get_x11_window_filter
    log("init_x11_window_filters() filters.get_window_filter=%s", filters.get_window_filter)
