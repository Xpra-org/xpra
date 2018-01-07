# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import gtk
import dbus.service

from xpra.log import Logger
log = Logger("dbus", "notify")

BUS_NAME="org.freedesktop.Notifications"
BUS_PATH="/org/freedesktop/Notifications"

"""
We register this class as handling notifications on the session dbus,
optionally replacing an existing instance if one exists.

The generalized callback signatures are:
 notify_callback(dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout)
 close_callback(nid)
"""
class DBUSNotificationsForwarder(dbus.service.Object):

    CAPABILITIES = ["body", "icon-static"]

    def __init__(self, bus, notify_callback=None, close_callback=None):
        self.bus = bus
        self.notify_callback = notify_callback
        self.close_callback = close_callback
        self.counter = 0
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        bus_name = dbus.service.BusName(BUS_NAME, bus=bus)
        dbus.service.Object.__init__(self, bus_name, BUS_PATH)

    @dbus.service.method(BUS_NAME, in_signature='susssasa{sv}i', out_signature='u')
    def Notify(self, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout):
        log("Notify(%s,%s,%s,%s,%s,%s,%s,%s)" % (app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout))
        if replaces_nid==0:
            self.counter += 1
            nid = self.counter
        else:
            nid = replaces_nid
        if self.notify_callback:
            self.notify_callback(self.dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout)
        log("Notify returning %s", nid)
        return nid

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
    def CloseNotification(self, nid):
        log("CloseNotification(%s)", nid)
        if self.close_callback:
            self.close_callback(nid)

    def release(self):
        try:
            self.bus.release_name(BUS_NAME)
        except Exception as e:
            log.error("failed to release dbus notification forwarder: %s", e)

    def __str__(self):
        return  "DBUS-NotificationsForwarder(%s)" % BUS_NAME

def register(notify_callback=None, close_callback=None, replace=False):
    from xpra.dbus.common import init_session_bus
    bus = init_session_bus()
    flags = dbus.bus.NAME_FLAG_DO_NOT_QUEUE
    if replace:
        flags |= dbus.bus.NAME_FLAG_REPLACE_EXISTING
    request = bus.request_name(BUS_NAME, flags)
    if request==dbus.bus.REQUEST_NAME_REPLY_EXISTS:
        raise Exception("the name '%s' is already claimed on the session bus" % BUS_NAME)
    log("notifications: bus name '%s', request=%s" % (BUS_NAME, request))
    return DBUSNotificationsForwarder(bus, notify_callback, close_callback)

def main():
    register()
    gtk.main()

if __name__ == "__main__":
    main()
