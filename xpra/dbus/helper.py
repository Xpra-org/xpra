#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger


def dbus_to_native(value):
    # log("dbus_to_native(%s) type=%s", value, type(value))
    if value is None:
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, dict):
        d = {}
        for k, v in value.items():
            d[dbus_to_native(k)] = dbus_to_native(v)
        return d
    if isinstance(value, str):
        return str(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, list):
        return [dbus_to_native(x) for x in value]
    from dbus import Struct
    if isinstance(value, Struct):
        return [dbus_to_native(value[i]) for i in range(len(value))]
    return value


def native_to_dbus(value, signature=None):
    try:
        from dbus import types
    except ImportError as e:
        raise RuntimeError(f"the dbus bindings are missing: {e}")
    if value is None:
        return None
    if isinstance(value, int):
        return types.Int64(value)
    if isinstance(value, str):
        return types.String(value)
    if isinstance(value, float):
        return types.Double(value)
    if isinstance(value, (tuple, list, bytearray)):
        if not value:
            return types.Array(signature="s")
        keytypes = set(type(x) for x in value)
        if not signature and len(keytypes) == 1:
            # just one type of key:
            keytype = tuple(keytypes)[0]
            if keytype is int:
                signature = "i"
            elif keytype is bool:
                signature = "b"
            elif keytype is float:
                signature = "d"
        if signature:
            value = [native_to_dbus(v) for v in value]
        else:
            signature = "s"
            # use strings as keys
            value = [native_to_dbus(str(v)) for v in value]
        return types.Array(value, signature=signature)
    if isinstance(value, dict):
        if not value:
            return types.Dictionary({}, signature=signature or "sv")
        if signature is None:
            keytypes = set(type(x) for x in value.keys())
            sig = None
            if len(keytypes) == 1:
                # just one type of key:
                keytype = tuple(keytypes)[0]
                if keytype is int:
                    sig = "i"
                elif keytype is bool:
                    sig = "b"
                elif keytype is float:
                    sig = "d"
            if sig:
                value = {k: native_to_dbus(v) for k, v in value.items()}
            else:
                sig = "s"
                # use strings as keys
                value = {str(k): native_to_dbus(v) for k, v in value.items()}
            signature = f"{sig}v"
        return types.Dictionary(value, signature=signature)
    return types.String(value)


class DBusHelper:

    def __init__(self):
        from xpra.dbus.common import init_session_bus
        self.bus = init_session_bus()

    def get_session_bus(self):
        return self.bus

    def dbus_to_native(self, *args):
        return dbus_to_native(*args)

    def call_function(self, bus_name, path, interface, function, args, ok_cb, err_cb) -> None:
        log = Logger("dbus")

        def err(msg) -> None:
            log("DBusHelper: %s", msg)
            err_cb(msg)

        from dbus import DBusException
        try:
            # remote_object = self.bus.get_object("com.example.SampleService","/SomeObject")
            obj = self.bus.get_object(bus_name, path)
            log("dbus.get_object(%s, %s)=%s", bus_name, path, obj)
        except DBusException:
            err("failed to locate object at: %s:%s" % (bus_name, path))
            return
        try:
            fn = obj.get_dbus_method(function, interface)
            log("%s.get_dbus_method(%s, %s)=%s", obj, function, interface, fn)
        except Exception:
            err("failed to locate remote function '%s' on %s" % (function, obj))
            return
        try:
            log("calling %s(%s)", fn, args)
            keywords = {"dbus_interface": interface,
                        "reply_handler": ok_cb,
                        "error_handler": err_cb}
            fn.call_async(*args, **keywords)
        except Exception as e:
            err("error invoking %s on %s: %s" % (function, obj, e))
