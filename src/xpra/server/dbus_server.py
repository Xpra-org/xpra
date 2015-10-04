#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.dbus.common import init_session_bus
import dbus.service

from xpra.log import Logger
log = Logger("dbus", "server")

INTERFACE = "org.xpra.Server"
PATH = "/org/xpra/Server"


class DBUS_Server(dbus.service.Object):

    def __init__(self, server=None, pathextra=""):
        self.server = server
        session_bus = init_session_bus()
        bus_name = dbus.service.BusName(INTERFACE, session_bus)
        dbus.service.Object.__init__(self, bus_name, PATH+pathextra)
        self.log("(%s)", server)


    def cleanup(self):
        self.remove_from_connection()


    def log(self, fmt, *args):
        log("%s"+fmt, INTERFACE, *args)


    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='v')
    def Get(self, property_name):
        raise dbus.exceptions.DBusException("this object does not have any properties")

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='', out_signature='a{sv}')
    def GetAll(self, interface_name):
        return []

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ssv')
    def Set(self, interface_name, property_name, new_value):
        self.PropertiesChanged(interface_name, { property_name: new_value }, [])

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
