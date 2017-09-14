#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import dbus.service

from xpra.log import Logger
log = Logger("dbus", "server")

BUS_NAME = "org.xpra.Server"
INTERFACE = "org.xpra.Server"
PATH = "/org/xpra/Server"


class DBUS_Server_Base(dbus.service.Object):

    def __init__(self, bus, server, name):
        self.server = server
        bus_name = dbus.service.BusName(name, bus)
        dbus.service.Object.__init__(self, bus_name, PATH)
        self.log("(%s)", server)
        self._properties = {}

    def cleanup(self):
        try:
            log("calling %s", self.remove_from_connection)
            self.remove_from_connection()
        except Exception as e:
            log.error("Error removing the DBUS server:")
            log.error(" %s", e)


    def log(self, fmt, *args):
        log("%s"+fmt, INTERFACE, *args)


    @dbus.service.signal(INTERFACE, signature='sas')
    def Event(self, event, args):
        self.log(".Event(%s, %s)", event, args);


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
