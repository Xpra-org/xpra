# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Callable
import dbus.service

from xpra.notification.common import parse_image_data, parse_image_path
from xpra.dbus.helper import dbus_to_native
from xpra.common import noop
from xpra.util.str_fn import csv
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("dbus", "notify")

BUS_NAME = "org.freedesktop.Notifications"
BUS_PATH = "/org/freedesktop/Notifications"

ACTIONS = envbool("XPRA_NOTIFICATIONS_ACTIONS", True)


def parse_hints(dbus_hints) -> dict:
    hints = {}
    h = dbus_to_native(dbus_hints)
    for x in ("image-data", "icon_data"):
        data = h.pop(x, None)
        if data:
            v = parse_image_data(data)
            if v:
                hints["image-data"] = v
                break
    if "image-data" not in hints:
        image_path = h.pop("image-path", "")
        v = parse_image_path(image_path)
        if v:
            hints["image-data"] = v
    for x in ("action-icons", "category", "desktop-entry", "resident", "transient", "x", "y", "urgency"):
        v = h.get(x)
        if v is not None:
            hints[x] = v
    log("parse_hints(%s)=%s", dbus_hints, hints)
    return hints


def get_capabilities() -> list[str]:
    caps = ["body", "icon-static"]
    if ACTIONS:
        caps += ["actions", "action-icons"]
    return caps


class DBUSNotificationsForwarder(dbus.service.Object):
    """
    We register this class as handling notifications on the session dbus,
    optionally replacing an existing instance if one exists.

    The generalized callback signatures are:
     notify_callback(dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout)
     close_callback(nid)
    """

    def __init__(self, bus, notify_callback: Callable = noop, close_callback: Callable = noop):
        self.bus = bus
        self.notify_callback = notify_callback
        self.close_callback = close_callback
        self.active_notifications = set()
        self.counter = 0
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        bus_name = dbus.service.BusName(BUS_NAME, bus=bus)
        super().__init__(bus_name, BUS_PATH)

    def get_info(self) -> dict[str, Any]:
        return {
            "active": tuple(self.active_notifications),
            "counter": self.counter,
            "dbus-id": self.dbus_id,
            "bus-name": BUS_NAME,
            "bus-path": BUS_PATH,
            "capabilities": get_capabilities(),
        }

    def next_id(self) -> int:
        self.counter += 1
        return self.counter

    @dbus.service.method(BUS_NAME, in_signature='susssasa{sv}i', out_signature='u')
    def Notify(self, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout):
        if replaces_nid == 0:
            nid = self.next_id()
        else:
            nid = int(replaces_nid)
        log("Notify%s nid=%s, counter=%i, callback=%s",
            (app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout),
            nid, self.counter, self.notify_callback)
        self.active_notifications.add(nid)
        if self.notify_callback:
            try:
                actions = tuple(str(x) for x in actions)
                hints = parse_hints(hints)
                args = (
                    self.dbus_id, int(nid), str(app_name),
                    int(replaces_nid), str(app_icon),
                    str(summary), str(body),
                    actions, hints, int(expire_timeout),
                )
            except Exception as e:
                log("Notify(..)", exc_info=True)
                log.error("Error: failed to parse Notify arguments:")
                log.estr(e)
                return 0
            with log.trap_error("Error calling notification handler"):
                self.notify_callback(*args)
        log("Notify returning %s", nid)
        return nid

    @dbus.service.method(BUS_NAME, out_signature='ssss')
    def GetServerInformation(self):
        # name, vendor, version, spec-version
        from xpra import __version__
        v = ["xpra-notification-proxy", "xpra", __version__, "0.9"]
        log("GetServerInformation()=%s", v)
        return v

    @dbus.service.method(BUS_NAME, out_signature='as')
    def GetCapabilities(self):
        caps = get_capabilities()
        log("GetCapabilities()=%s", csv(caps))
        return caps

    @dbus.service.method(BUS_NAME, in_signature='u')
    def CloseNotification(self, nid) -> None:
        log("CloseNotification(%s) callback=%s", nid, self.close_callback)
        try:
            self.active_notifications.remove(int(nid))
        except KeyError:
            return
        else:
            if self.close_callback:
                self.close_callback(nid)
            self.NotificationClosed(nid, 3)  # 3="The notification was closed by a call to CloseNotification"

    def is_notification_active(self, nid) -> bool:
        return nid in self.active_notifications

    @dbus.service.signal(BUS_NAME, signature='uu')
    def NotificationClosed(self, nid, reason) -> None:
        log(f"NotificationClosed({nid}, {reason})")

    @dbus.service.signal(BUS_NAME, signature='us')
    def ActionInvoked(self, nid, action_key) -> None:
        log(f"ActionInvoked({nid}, {action_key})")

    def release(self) -> None:
        try:
            self.bus.release_name(BUS_NAME)
        except dbus.exceptions.DBusException as e:
            log("release()", exc_info=True)
            log.error("Error releasing the dbus notification forwarder:")
            for x in str(e).split(": "):
                log.estr(x)

    def __str__(self):
        return f"DBUS-NotificationsForwarder({BUS_NAME})"


def register(notify_callback: Callable = noop, close_callback: Callable = noop, replace=False):
    from xpra.dbus.common import init_session_bus
    bus = init_session_bus()
    flags = dbus.bus.NAME_FLAG_DO_NOT_QUEUE
    if replace:
        flags |= dbus.bus.NAME_FLAG_REPLACE_EXISTING
    request = bus.request_name(BUS_NAME, flags)
    log(f"notifications: bus name {BUS_NAME!r}, request={request}")
    if request == dbus.bus.REQUEST_NAME_REPLY_EXISTS:
        raise ValueError(f"the name {BUS_NAME!r} is already claimed on the session bus")
    return DBUSNotificationsForwarder(bus, notify_callback, close_callback)


def main() -> None:
    register()
    from xpra.os_util import gi_import
    glib = gi_import("GLib")
    mainloop = glib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()
