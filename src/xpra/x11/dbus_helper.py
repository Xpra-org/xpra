#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import dbus
from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_DBUS_DEBUG")


class DBusHelper(object):

    def __init__(self):
        from xpra.x11.dbus_common import init_session_bus
        self.bus = init_session_bus()

    def call_function(self, bus_name, path, interface, function, args, ok_cb, err_cb):
        try:
            #remote_object = self.bus.get_object("com.example.SampleService","/SomeObject")
            obj = self.bus.get_object(bus_name, path)
            debug("dbus.get_object(%s, %s)=%s", bus_name, path, obj)
        except dbus.DBusException:
            err_cb("failed to locate object at: %s:%s" % (bus_name, path))
            return
        try:
            fn = obj.get_dbus_method(function, interface)
            debug("%s.get_dbus_method(%s, %s)=%s", obj, function, interface, fn)
        except:
            err_cb("failed to locate remote function '%s' on %s" % (function, obj))
            return
        try:
            debug("calling %s(%s)", fn, args)
            fn(*args, dbus_interface=interface, reply_handler=ok_cb, error_handler=err_cb)
        except Exception, e:
            err_cb("error invoking %s on %s: %s", function, obj, e)

    def dbus_to_native(self, value):
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
                d[self.dbus_to_native(k)] = self.dbus_to_native(v)
            return d
        elif isinstance(value, unicode):
            return str(value)
        elif isinstance(value, basestring):
            return str(value)
        elif isinstance(value, float):
            return float(value)
        elif isinstance(value, list):
            return [self.dbus_to_native(x) for x in value]
        return value
