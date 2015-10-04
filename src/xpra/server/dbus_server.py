#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.dbus.helper import dbus_to_native
from xpra.dbus.common import init_session_bus
import dbus.service

from xpra.log import Logger
log = Logger("dbus", "server")

INTERFACE = "org.xpra.Server"
PATH = "/org/xpra/Server"


def n(*args):
    return dbus_to_native(*args)
def ni(*args):
    return int(n(*args))
def ns(*args):
    return str(n(*args))


class DBUS_Server(dbus.service.Object):

    def __init__(self, server=None, pathextra=""):
        self.server = server
        session_bus = init_session_bus()
        bus_name = dbus.service.BusName(INTERFACE, session_bus)
        dbus.service.Object.__init__(self, bus_name, PATH+pathextra)
        self.log("(%s)", server)
        self._properties = {"idle-timeout"          : ("idle_timeout", ni),
                            "server-idle-timeout"   : ("server_idle_timeout", ni),
                            "name"                  : ("session_name", ns),
                            }

    def cleanup(self):
        self.remove_from_connection()


    def log(self, fmt, *args):
        log("%s"+fmt, INTERFACE, *args)


    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='v')
    def Get(self, property_name):
        conv = self._properties.get(property_name)
        if conv is None:
            raise dbus.exceptions.DBusException("invalid property")
        server_property_name, _ = conv
        v = getattr(self.server, server_property_name)
        self.log(".Get(%s)=%s", property_name, v)
        return v

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='', out_signature='a{sv}')
    def GetAll(self, interface_name):
        if interface_name==INTERFACE:
            v = dict((x, self.Get(x)) for x in self._properties.keys())
        else:
            v = {}
        self.log(".GetAll(%s)=%s", interface_name, v)
        return v

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ssv')
    def Set(self, interface_name, property_name, new_value):
        self.log(".Set(%s, %s, %s)", interface_name, property_name, new_value)
        conv = self._properties.get(property_name)
        if conv is None:
            raise dbus.exceptions.DBusException("invalid property")
        server_property_name, validator = conv
        assert hasattr(self.server, server_property_name)
        setattr(self.server, server_property_name, validator(new_value))

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface_name, changed_properties, invalidated_properties):
        pass


    @dbus.service.method(INTERFACE, in_signature='i')
    def Focus(self, wid):
        self.server.control_command_focus(wid)

    @dbus.service.method(INTERFACE, in_signature='')
    def Suspend(self):
        self.server.control_command_suspend()

    @dbus.service.method(INTERFACE, in_signature='')
    def Resume(self):
        self.server.control_command_resume()

    @dbus.service.method(INTERFACE, in_signature='')
    def Ungrab(self):
        self.server.control_command_resume()


    @dbus.service.method(INTERFACE, in_signature='s')
    def Start(self, command):
        self.server.do_control_command_start(True, command)

    @dbus.service.method(INTERFACE, in_signature='s')
    def StartChild(self, command):
        self.server.do_control_command_start(False, command)


    @dbus.service.method(INTERFACE, in_signature='s')
    def KeyPress(self, keycode):
        self.server.control_command_key(keycode, press=True)

    @dbus.service.method(INTERFACE, in_signature='s')
    def KeyRelease(self, keycode):
        self.server.control_command_key(keycode, press=False)
