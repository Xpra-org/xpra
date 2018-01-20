#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import dbus
from xpra.log import Logger
log = Logger("dbus")

PY3 = sys.version_info[0]==3
if PY3:
    long = int          #@ReservedAssignment
    basestring = str    #@ReservedAssignment


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
    elif isinstance(value, basestring):
        return str(value)
    elif isinstance(value, float):
        return float(value)
    elif isinstance(value, list):
        return [dbus_to_native(x) for x in value]
    elif isinstance(value, dbus.Struct):
        return [dbus_to_native(value[i]) for i in range(len(value))]
    return value

def native_to_dbus(value):
    if value is None:
        return None
    elif isinstance(value, int):
        return dbus.types.Int64(value)
    elif isinstance(value, long):
        return dbus.types.Int64(value)
    elif isinstance(value, unicode):
        return dbus.types.String(value)
    elif isinstance(value, basestring):
        return dbus.types.String(value)
    elif isinstance(value, float):
        return dbus.types.Double(value)
    elif isinstance(value, (tuple, list, bytearray)):
        if not value:
            return dbus.Array(signature="s")
        keytypes = set([type(x) for x in value])
        sig = None
        if len(keytypes)==1:
            #just one type of key:
            keytype = tuple(keytypes)[0]
            if keytype is int:
                sig = "i"
            if keytype is long:
                sig = "x"
            elif keytype is bool:
                sig = "b"
            elif keytype is float:
                sig = "d"
        if sig:
            value = [native_to_dbus(v) for v in value]
        else:
            sig = "s"
            #use strings as keys
            value = [native_to_dbus(str(v)) for v in value]
        return dbus.types.Array(value)
    elif isinstance(value, dict):
        if not value:
            return dbus.types.Dictionary({}, signature="sv")
        keytypes = set([type(x) for x in value.keys()])
        sig = None
        if len(keytypes)==1:
            #just one type of key:
            keytype = tuple(keytypes)[0]
            if keytype is int:
                sig = "i"
            if keytype is long:
                sig = "x"
            elif keytype is bool:
                sig = "b"
            elif keytype is float:
                sig = "d"
        if sig:
            value = dict((k, native_to_dbus(v)) for k,v in value.items())
        else:
            sig = "s"
            #use strings as keys
            value = dict((str(k), native_to_dbus(v)) for k,v in value.items())
        return dbus.types.Dictionary(value, signature="%sv" % sig)
    return dbus.types.String(value)


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
