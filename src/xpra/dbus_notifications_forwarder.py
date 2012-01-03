# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import gtk
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

from wimpiggy.log import Logger
log = Logger()

BUS_NAME="org.freedesktop.Notifications"
BUS_PATH="/org/freedesktop/Notifications"

"""
We register this class as handling notifications on the session dbus,
optionally replacing an existing instance if one exists.

The generalized callback signatures are:
 notify_callback(dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout)
 close_callback(id)
"""
class DBUSNotificationsForwarder(dbus.service.Object):

    CAPABILITIES = ["body", "icon-static"]

    def __init__(self, bus, notify_callback=None, close_callback=None):
        self.notify_callback = notify_callback
        self.close_callback = close_callback
        self.counter = 0
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        bus_name = dbus.service.BusName(BUS_NAME, bus=bus)
        dbus.service.Object.__init__(self, bus_name, BUS_PATH)
 
    @dbus.service.method(BUS_NAME, in_signature='susssasa{sv}i', out_signature='u')
    def Notify(self, app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout):
        log("Notify(%s,%s,%s,%s,%s,%s,%s,%s)" % (app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout))
        if replaces_id==0:
            self.counter += 1
            id = self.counter
        else:
            id = replaces_id
        if self.notify_callback:
            self.notify_callback(self.dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout)
        log("Notify returning %s", id)
        return id

    @dbus.service.method(BUS_NAME, out_signature='ssss')
    def GetServerInformation(self):
        log("GetServerInformation()")
        #name, vendor, version, spec-version
        return    ["xpra-notification-proxy", "xpra", "0.1", "0.9"]

    @dbus.service.method(BUS_NAME, out_signature='as')
    def GetCapabilities(self):
        log("GetCapabilities()")
        return DBUSNotificationsForwarder.CAPABILITIES

    @dbus.service.method(BUS_NAME, in_signature='u')
    def CloseNotification(self, id):
        log("CloseNotification(%s)", id)
        if self.close_callback:
            self.close_callback(id)

def register(notify_callback=None, close_callback=None, replace=False):
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    if replace:
        request = bus.request_name(BUS_NAME, dbus.bus.NAME_FLAG_REPLACE_EXISTING)
        log("request_name(%s)=%s" % (BUS_NAME, request))
    return DBUSNotificationsForwarder(bus, notify_callback, close_callback)

def main():
    register()
    gtk.main()

if __name__ == "__main__":
    main()
