#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence
from Foundation import NSUserNotificationCenter, NSUserNotification, NSUserNotificationDefaultSoundName

from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.notification.base import NotifierBase, NID
from xpra.log import Logger

log = Logger("notify")

GLib = gi_import("GLib")


class OSX_Notifier(NotifierBase):

    def __init__(self, closed_cb=None, action_cb=None):
        super().__init__(closed_cb, action_cb)
        self.gtk_notifier = None
        self.gtk_notifications = set()
        self.notifications = {}
        self.notification_center = NSUserNotificationCenter.defaultUserNotificationCenter()
        assert self.notification_center

    def show_notify(self, dbus_id: str, tray, nid: NID,
                    app_name: str, replaces_nid: NID, app_icon: str,
                    summary: str, body: str,
                    actions: Sequence[str], hints: dict, expire_timeout: int, icon):
        GTK_NOTIFIER = envbool("XPRA_OSX_GTK_NOTIFIER", True)
        if actions and GTK_NOTIFIER:
            # try to use GTK notifier if we have actions buttons to handle:
            try:
                from xpra.gtk.notifier import GTKNotifier
            except ImportError as e:
                log("cannot use GTK notifier for handling actions: %s", e)
            else:
                self.gtk_notifier = GTKNotifier(self.closed_cb, self.action_cb)
                self.gtk_notifier.show_notify(dbus_id, tray, nid, app_name, replaces_nid, app_icon,
                                              summary, body, actions, hints, expire_timeout, icon)
                self.gtk_notifications.add(nid)
                return
        GLib.idle_add(self.do_show_notify, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, actions,
                      hints, expire_timeout, icon)

    def do_show_notify(self, dbus_id: str, tray, nid: NID, app_name: str,
                       replaces_nid: NID, app_icon: str,
                       summary: str, body: str, actions, hints, expire_timeout: int, icon):
        notification = NSUserNotification.alloc()
        notification.init()
        notification.setTitle_(summary)
        notification.setInformativeText_(body)
        notification.setIdentifier_("%s" % nid)
        # enable sound:
        notification.setSoundName_(NSUserNotificationDefaultSoundName)
        log("do_show_notify(..) nid=%s, %s(%s)", nid, self.notification_center.deliverNotification_, notification)
        self.notifications[int(nid)] = notification
        self.notification_center.deliverNotification_(notification)

    def close_notify(self, nid: NID):
        try:
            self.gtk_notifications.remove(int(nid))
        except KeyError:
            notification = self.notifications.get(int(nid))
            log("close_notify(..) notification[%i]=%s", nid, notification)
            if notification:
                GLib.idle_add(self.notification_center.removeDeliveredNotification_, notification)
        else:
            self.gtk_notifier.close_notify(int(nid))

    def cleanup(self):
        super().cleanup()
        GLib.idle_add(self.notification_center.removeAllDeliveredNotifications)
