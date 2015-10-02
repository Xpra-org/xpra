#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import dbus
from xpra.log import Logger
log = Logger("dbus")


def dbus_to_native(value):
    #log("dbus_to_native(%s) type=%s", value, type(value))
    if value is None:
        return None
    elif isinstance(value, int):
        return int(value)
    elif isinstance(value, long):
        return long(value)
    elif isinstance(value, dict):
        d = {}
        for k,v in value.items():
            d[dbus_to_native(k)] = dbus_to_native(v)
        return d
    elif isinstance(value, unicode):
        return str(value)
    elif isinstance(value, basestring):
        return str(value)
    elif isinstance(value, float):
        return float(value)
    elif isinstance(value, list):
        return [dbus_to_native(x) for x in value]
    elif isinstance(value, dbus.Struct):
        return [dbus_to_native(value[i]) for i in range(len(value))]
    return value

class DBusHelper(object):

    def __init__(self):
        from xpra.dbus.common import init_session_bus
        self.bus = init_session_bus()

    def get_session_bus(self):
        return self.bus

    def dbus_to_native(self, *args):
        return dbus_to_native(*args)


    def call_function(self, bus_name, path, interface, function, args, ok_cb, err_cb):
        try:
            #remote_object = self.bus.get_object("com.example.SampleService","/SomeObject")
            obj = self.bus.get_object(bus_name, path)
            log("dbus.get_object(%s, %s)=%s", bus_name, path, obj)
        except dbus.DBusException:
            msg = "failed to locate object at: %s:%s" % (bus_name, path)
            log("DBusHelper: %s", msg)
            err_cb(msg)
            return
        try:
            fn = obj.get_dbus_method(function, interface)
            log("%s.get_dbus_method(%s, %s)=%s", obj, function, interface, fn)
        except:
            msg = "failed to locate remote function '%s' on %s" % (function, obj)
            log("DBusHelper: %s", msg)
            err_cb(msg)
            return
        try:
            log("calling %s(%s)", fn, args)
            keywords = {"dbus_interface"        : interface,
                        "reply_handler"         : ok_cb,
                        "error_handler"         : err_cb}
            fn.call_async(*args, **keywords)
        except Exception as e:
            msg = "error invoking %s on %s: %s" % (function, obj, e)
            log("DBusHelper: %s", msg)
            err_cb(msg)
