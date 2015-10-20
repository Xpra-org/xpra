#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.dbus.dbus_server import DBUS_Server, INTERFACE
import dbus.service

from xpra.log import Logger
log = Logger("dbus", "server")


class Shadow_DBUS_Server(DBUS_Server):

    @dbus.service.method(INTERFACE, in_signature='i')
    def SetRefreshDelay(self, milliseconds):
        return self.server.set_refresh_delay(milliseconds)
