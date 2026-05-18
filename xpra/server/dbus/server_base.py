#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final

import dbus.service  # @UnresolvedImport
from dbus import PROPERTIES_IFACE  # @UnresolvedImport
from dbus.exceptions import DBusException  # @UnresolvedImport

from xpra.dbus.helper import dbus_to_native
from xpra.log import Logger

log = Logger("dbus", "server")

BUS_NAME: Final[str] = "org.xpra.Server"
INTERFACE: Final[str] = "org.xpra.Server"
PATH: Final[str] = "/org/xpra/Server"


class DBUS_Server_Base(dbus.service.Object):

    def __init__(self, bus, server, name):
        self.server = server
        bus_name = dbus.service.BusName(name, bus)
        super().__init__(bus_name, PATH)
        self.log("(%s)", server)
        self._properties = {}

    def cleanup(self) -> None:
        try:
            log("calling %s", self.remove_from_connection)
            self.remove_from_connection()
        except Exception as e:  # pragma: no cover
            log.error("Error removing the DBUS server:")
            log.estr(e)

    def log(self, fmt, *args):
        log("%s" + fmt, INTERFACE, *args)

    @dbus.service.signal(INTERFACE, signature='sas')
    def Event(self, event, args):
        self.log(".Event(%s, %s)", event, args)

    def _resolve_property(self, server_property_name: str):
        """
        Resolve a property mapping target.
        A bare name (e.g. "session_name") refers to an attribute on the
        server; a dotted name (e.g. "idle.timeout") routes to an
        attribute on a subsystem instance via `server.subsystems[prefix]`.
        Returns `(target, attr_name)` or `(None, None)` if the subsystem
        is not available.
        """
        if "." in server_property_name:
            prefix, attr = server_property_name.split(".", 1)
            target = self.server.subsystems.get(prefix)
            if target is None:
                return None, None
            return target, attr
        return self.server, server_property_name

    @dbus.service.method(PROPERTIES_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface_name, property_name):
        conv = self._properties.get(property_name)
        if conv is None:
            raise DBusException("invalid property")
        server_property_name, _ = conv
        target, attr = self._resolve_property(server_property_name)
        if target is None:
            raise DBusException(f"subsystem not available for property {property_name!r}")
        v = getattr(target, attr)
        self.log(".Get(%s, %s)=%s", interface_name, property_name, v)
        return v

    @dbus.service.method(PROPERTIES_IFACE, in_signature='', out_signature='a{sv}')
    def GetAll(self, interface_name):
        v = {}
        if interface_name == PROPERTIES_IFACE:
            for x, conv in self._properties.items():
                target, attr = self._resolve_property(conv[0])
                if target is None:
                    # skip attributes whose subsystem is not available:
                    continue
                v[x] = getattr(target, attr)
        self.log(".GetAll(%s)=%s", interface_name, v)
        return v

    @dbus.service.method(PROPERTIES_IFACE, in_signature='ssv')
    def Set(self, interface_name, property_name, new_value):
        self.log(".Set(%s, %s, %s)", interface_name, property_name, new_value)
        conv = self._properties.get(property_name)
        if conv is None:
            raise DBusException("invalid property")
        server_property_name, validator = conv
        target, attr = self._resolve_property(server_property_name)
        if target is None:
            raise DBusException(f"subsystem not available for property {property_name!r}")
        assert hasattr(target, attr)
        setattr(target, attr, validator(new_value))

    @dbus.service.signal(PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface_name, changed_properties, invalidated_properties):
        n = dbus_to_native
        self.log(f"PropertiesChanged({interface_name}, {n(changed_properties)}, {n(invalidated_properties)})")
