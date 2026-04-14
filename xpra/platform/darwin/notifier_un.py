#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence
from UserNotifications import (
    UNUserNotificationCenter,
    UNMutableNotificationContent,
    UNNotificationSound,
    UNNotificationRequest,
    UNAuthorizationOptionAlert,
    UNAuthorizationOptionSound,
    UNAuthorizationOptionBadge,
)

from xpra.common import noop
from xpra.notification.common import IconData
from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.notification.base import NotifierBase, NID
from xpra.log import Logger

log = Logger("notify")

GLib = gi_import("GLib")


class UN_Notifier(NotifierBase):
    """
    macOS notification backend using UNUserNotificationCenter
    (UserNotifications framework, macOS 10.14+).
    Preferred over the deprecated NSUserNotificationCenter.
    """

    def __init__(self, closed_cb=noop, action_cb=noop):
        super().__init__(closed_cb, action_cb)
        self.gtk_notifier = None
        self.gtk_notifications: set[int] = set()
        self.notifications: dict[int, str] = {}  # nid -> request identifier
        self.notification_center = UNUserNotificationCenter.currentNotificationCenter()
        assert self.notification_center, "UNUserNotificationCenter is not available"
        options = UNAuthorizationOptionAlert | UNAuthorizationOptionSound | UNAuthorizationOptionBadge
        self.notification_center.requestAuthorizationWithOptions_completionHandler_(
            options, self._authorization_handler,
        )

    def _authorization_handler(self, granted: bool, error) -> None:
        if error:
            log.warn("Warning: UNUserNotificationCenter authorization error: %s", error)
        elif not granted:
            log.warn("Warning: UNUserNotificationCenter authorization was denied")
        else:
            log("UNUserNotificationCenter authorization granted")

    def show_notify(self, dbus_id: str, tray, nid: NID,
                    app_name: str, replaces_nid: NID, app_icon: str,
                    summary: str, body: str,
                    actions: Sequence[str], hints: dict, expire_timeout: int, icon: IconData | None):
        GTK_NOTIFIER = envbool("XPRA_OSX_GTK_NOTIFIER", True)
        if actions and GTK_NOTIFIER:
            # use GTK notifier when action buttons are needed:
            try:
                from xpra.gtk.notifier import GTKNotifier
            except ImportError as e:
                log("cannot use GTK notifier for handling actions: %s", e)
            else:
                self.gtk_notifier = GTKNotifier(self.closed_cb, self.action_cb)
                self.gtk_notifier.show_notify(dbus_id, tray, nid, app_name, replaces_nid, app_icon,
                                              summary, body, actions, hints, expire_timeout, icon)
                self.gtk_notifications.add(int(nid))
                return
        GLib.idle_add(self.do_show_notify, dbus_id, tray, nid, app_name, replaces_nid, app_icon,
                      summary, body, actions, hints, expire_timeout, icon)

    def do_show_notify(self, dbus_id: str, tray, nid: NID, app_name: str,
                       replaces_nid: NID, app_icon: str,
                       summary: str, body: str, actions, hints, expire_timeout: int, icon) -> None:
        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(summary)
        content.setBody_(body)
        content.setSound_(UNNotificationSound.defaultSound())
        identifier = str(int(nid))
        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(identifier, content, None)
        log("do_show_notify(..) nid=%s, identifier=%r, request=%s", nid, identifier, request)
        self.notifications[int(nid)] = identifier
        self.notification_center.addNotificationRequest_withCompletionHandler_(request, None)

    def close_notify(self, nid: NID) -> None:
        nid_int = int(nid)
        if nid_int in self.gtk_notifications:
            self.gtk_notifications.discard(nid_int)
            if self.gtk_notifier:
                self.gtk_notifier.close_notify(nid_int)
            return
        identifier = self.notifications.pop(nid_int, None)
        log("close_notify(%s) identifier=%r", nid, identifier)
        if identifier:
            GLib.idle_add(
                self.notification_center.removeDeliveredNotificationsWithIdentifiers_,
                [identifier],
            )

    def cleanup(self) -> None:
        super().cleanup()
        GLib.idle_add(self.notification_center.removeAllDeliveredNotifications)
