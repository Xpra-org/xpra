#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import dbus.service

from xpra.server.dbus.server import DBUS_Server, INTERFACE
from xpra.log import Logger

log = Logger("dbus", "server")


class X11_DBUS_Server(DBUS_Server):

    @dbus.service.method(INTERFACE)
    def SyncXvfb(self):
        self.server.do_repaint_root_overlay()

    @dbus.service.method(INTERFACE)
    def ResetXSettings(self):
        self.server.update_all_server_settings(True)

    @dbus.service.method(INTERFACE, in_signature='ii')
    def SetDPI(self, xdpi, ydpi):
        self.server.set_dpi(xdpi, ydpi)

    @dbus.service.method(INTERFACE, in_signature='ii', out_signature='ii')
    def SetScreenSize(self, width, height):
        return self.server.set_screen_size(width, height)

    @dbus.service.method(INTERFACE)
    def ShowAllWindows(self):
        self.server.show_all_windows()
