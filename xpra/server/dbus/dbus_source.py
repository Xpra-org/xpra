#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import dbus.service

from xpra.dbus.helper import dbus_to_native
from xpra.dbus.common import init_session_bus
from xpra.util import AtomicInteger, DETACH_REQUEST
from xpra.log import Logger

log = Logger("dbus", "server")

BUS_NAME = "org.xpra.Server"
INTERFACE = "org.xpra.Client"
PATH = "/org/xpra/Client"

def n(*args):
    return dbus_to_native(*args)
def ni(*args):
    return int(n(*args))
def nb(*args):
    return bool(n(*args))
def ns(*args):
    return str(n(*args))


sequence = AtomicInteger()

class DBUS_Source(dbus.service.Object):
    SUPPORTS_MULTIPLE_OBJECT_PATHS = True

    def __init__(self, source=None, extra=""):
        self.source = source
        session_bus = init_session_bus()
        name = BUS_NAME
        self.path = PATH + str(sequence.increase())
        if extra:
            name += extra.replace(".", "_").replace(":", "_")
        bus_name = dbus.service.BusName(name, session_bus)
        dbus.service.Object.__init__(self, bus_name, self.path)
        self.log("(%s)", source)
        self._properties = {"bell"              : ("send_bell",             ni),
                            "cursors"           : ("send_cursors",          ni),
                            "notifications"     : ("send_notifications",    ni),
                            }

    def __str__(self):
        return "DBUS_Source(%s:%s)" % (BUS_NAME, self.path)


    def cleanup(self):
        try:
            log("calling %s", self.remove_from_connection)
            self.remove_from_connection()
        except Exception as e:
            log.error("Error removing the source's DBUS server:")
            log.error(" %s", e)


    def log(self, fmt, *args):
        log("%s"+fmt, INTERFACE, *args)


    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='v')
    def Get(self, property_name):
        conv = self._properties.get(property_name)
        if conv is None:
            raise dbus.exceptions.DBusException("invalid property")
        server_property_name, _ = conv
        v = getattr(self.source, server_property_name)
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
        assert hasattr(self.source, server_property_name)
        setattr(self.source, server_property_name, validator(new_value))

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface_name, changed_properties, invalidated_properties):
        pass


    @dbus.service.method(INTERFACE, in_signature='b')
    def ShowDesktop(self, show):
        show = nb(show)
        self.log(".ShowDesktop(%s)", show)
        self.source.show_desktop(show)

    @dbus.service.method(INTERFACE, in_signature='i')
    def RaiseWindow(self, wid):
        wid = ni(wid)
        self.log(".RaiseWindow(%s)", wid)
        self.source.raise_window(wid)

    @dbus.service.method(INTERFACE, in_signature='')
    def ResetWindowFilters(self):
        self.log(".ResetWindowFilters()")
        self.source.reset_window_filters()

    @dbus.service.method(INTERFACE, in_signature='sssv')
    def AddWindowFilter(self, object_name, property_name, operator, value):
        self.log(".AddWindowFilter%s", (object_name, property_name, operator, value))
        self.source.add_window_filter(ns(object_name), ns(property_name), ns(operator), n(value))

    @dbus.service.method(INTERFACE, out_signature='as')
    def GetAllWindowFilters(self):
        v = [str(x) for x in self.source.get_all_window_filters()]
        self.log(".GetAllWindowFilters()=%s", v)
        return v


    @dbus.service.method(INTERFACE, in_signature='')
    def SetDefaultKeymap(self):
        self.log(".SetDefaultKeymap()")
        self.source.set_default_keymap()


    @dbus.service.method(INTERFACE, in_signature='')
    def Suspend(self):
        self.log(".Suspend()")
        self.source.go_idle()

    @dbus.service.method(INTERFACE, in_signature='')
    def Resume(self):
        self.log(".Resume()")
        self.source.no_idle()


    @dbus.service.method(INTERFACE, in_signature='s')
    def StartSpeaker(self, codec):
        codec = ns(codec)
        self.log(".StartSpeaker(%s)", codec)
        self.source.start_sending_sound(codec)

    @dbus.service.method(INTERFACE, in_signature='')
    def StopSpeaker(self):
        self.log(".StopSpeaker()")
        self.source.stop_sending_sound()


    @dbus.service.method(INTERFACE, in_signature='i')
    def SetAVSyncDelay(self, delay):
        d = ni(delay)
        self.log(".SetAVSyncDelay(%i)", d)
        self.source.set_av_sync_delay(d)


    @dbus.service.method(INTERFACE, in_signature='as')
    def SendClientCommand(self, args):
        cmd = n(args)
        self.log(".SendClientCommand(%s)", cmd)
        self.source.send_client_command(*cmd)


    @dbus.service.method(INTERFACE, in_signature='s')
    def Detach(self, reason):
        proto = self.source.proto
        rs = ns(reason)
        self.log(".SendClientCommand(%s) protocol=%s", rs, proto)
        assert proto, "no connection"
        proto.send_disconnect(DETACH_REQUEST, rs)
