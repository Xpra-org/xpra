# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2015-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.source.client_connection import ClientConnection
from xpra.gtk_common.gobject_compat import get_xid
from xpra.gtk_common.error import xsync
from xpra.x11.gtk_x11.prop import prop_get, get_python_type
from xpra.x11.bindings.window_bindings import X11WindowBindings     #@UnresolvedImport
window_bindings = X11WindowBindings()

from xpra.log import Logger
log = Logger("x11", "server")


def get_x11_window_value(filter_object, window):
    xid = get_xid(window)
    #log("get_x11_window_value(%s, %s) xid=%#x", filter_object, window, xid)
    with xsync:
        x11type = window_bindings.GetWindowPropertyType(xid, filter_object.property_name)
        ptype = get_python_type(x11type)
        #log("%s: %s (%s)", filter_object.property_name, x11type, ptype)
        assert ptype, "type '%s' is not handled!" % x11type
        v = prop_get(window, filter_object.property_name, ptype)
    log("%s=%s", filter_object.property_name, v)
    return v


class X11ServerSource(ClientConnection):
    """ Adds the ability to filter windows using X11 properties """

    def get_window_filter(self, object_name, property_name, operator, value):
        if object_name.lower() not in ("x11window", "window"):
            raise ValueError("invalid object name")
        wf = ClientConnection.get_window_filter(self, "window", property_name, operator, value)
        if object_name.lower()=="x11window":
            #same filter but use X11 properties:
            def get_window_value(window):
                return get_x11_window_value(wf, window)
            wf.get_window_value = get_window_value
        log("get_window_filter%s=%s", (object_name, property_name, operator, value), wf)
        return wf
