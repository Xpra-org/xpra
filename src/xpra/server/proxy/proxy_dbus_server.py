#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

import dbus.service

from xpra.dbus.helper import native_to_dbus
from xpra.dbus.common import init_system_bus, init_session_bus
from xpra.server.dbus.dbus_server import DBUS_Server_Base, INTERFACE, BUS_NAME
from xpra.log import Logger

log = Logger("dbus", "server")


class Proxy_DBUS_Server(DBUS_Server_Base):

    def __init__(self, server=None):
        if os.getuid()==0:
            bus = init_system_bus()
        else:
            bus = init_session_bus()
        DBUS_Server_Base.__init__(self, bus, server, BUS_NAME)

    @dbus.service.method(INTERFACE, in_signature='', out_signature='a{sv}')
    def GetInfo(self):
        #full info is available by calling get_info()
        i = self.server.get_minimal_server_info()
        self.log(".GetInfo()=%s", i)
        try:
            v =  dbus.types.Dictionary((str(k), native_to_dbus(v)) for k,v in i.items())
            log("native_to_dbus(..)=%s", v)
        except Exception:
            log("GetInfo:gotinfo", exc_info=True)
            v = dbus.types.Dictionary({})
        return v
