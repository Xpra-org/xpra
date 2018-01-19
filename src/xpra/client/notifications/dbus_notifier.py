# This file is part of Xpra.
# Copyright (C) 2011-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import repr_ellipsized, csv
from xpra.client.notifications.notifier_base import NotifierBase, log
try:
    #new recommended way of using the glib main loop:
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
except:
    #beware: this import has side-effects:
    import dbus.glib
    assert dbus.glib
import dbus.exceptions

NOTIFICATION_APP_NAME = os.environ.get("XPRA_NOTIFICATION_APP_NAME", "%s (via Xpra)")


def DBUS_Notifier_factory(*args):
    try:
        return DBUS_Notifier(*args)
    except Exception as e:
        log.warn("failed to instantiate the dbus notification handler:")
        if str(e).startswith("org.freedesktop.DBus.Error.ServiceUnknown:"):
            log.warn(" you may need to start a notification service for 'org.freedesktop.Notifications'")
        else:
            log.warn(" %s", e)
        log.warn(" disable notifications to avoid this warning")
        return None

class DBUS_Notifier(NotifierBase):

    def __init__(self, *args):
        NotifierBase.__init__(self, *args)
        self.app_name_format = NOTIFICATION_APP_NAME
        self.last_notification = None
        self.actual_notification_id = {}
        self.setup_dbusnotify()

    def setup_dbusnotify(self):
        self.dbus_session = dbus.SessionBus()
        FD_NOTIFICATIONS = 'org.freedesktop.Notifications'
        self.org_fd_notifications = self.dbus_session.get_object(FD_NOTIFICATIONS, '/org/freedesktop/Notifications')
        self.org_fd_notifications.connect_to_signal("NotificationClosed", self.NotificationClosed)
        self.org_fd_notifications.connect_to_signal("ActionInvoked", self.ActionInvoked)

        #connect_to_signal("HelloSignal", hello_signal_handler, dbus_interface="com.example.TestService", arg0="Hello")
        self.dbusnotify = dbus.Interface(self.org_fd_notifications, FD_NOTIFICATIONS)
        log("using dbusnotify: %s(%s)", type(self.dbusnotify), FD_NOTIFICATIONS)
        log("capabilities=%s", csv(str(x) for x in self.dbusnotify.GetCapabilities()))
        log("dbus.get_default_main_loop()=%s", dbus.get_default_main_loop())

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon):
        if not self.dbus_check(dbus_id):
            return
        self.may_retry = True
        try:
            icon_string = self.get_icon_string(nid, app_icon, icon)
            log("get_icon_string%s=%s", (nid, app_icon, repr_ellipsized(str(icon))), icon_string)
            try:
                app_str = self.app_name_format % app_name
            except:
                app_str = app_name or "Xpra"
            self.last_notification = (dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, icon)
            def NotifyReply(notification_id):
                log("NotifyReply(%s) for nid=%i", notification_id, nid)
                self.actual_notification_id[nid] = int(notification_id)
            self.dbusnotify.Notify(app_str, 0, icon_string, summary, body, actions, hints, expire_timeout,
                 reply_handler = NotifyReply,
                 error_handler = self.NotifyError)
        except:
            log.error("Error: dbus notify failed", exc_info=True)

    def _find_nid(self, actual_id):
        aid = int(actual_id)
        for k,v in self.actual_notification_id.items():
            if v==aid:
                return k
        return None

    def NotificationClosed(self, actual_id, reason):
        nid = self._find_nid(actual_id)
        reason_str = {
             1  : "expired",
             2  : "dismissed by the user",
             3  : "closed by a call to CloseNotification",
             4  : "Undefined/reserved reasons",
            }.get(int(reason), str(reason))
        log("NotificationClosed(%s, %s) nid=%s, reason=%s", actual_id, reason, nid, reason_str)
        if nid:
            try:
                self.actual_notification_id.pop(nid)
            except KeyError:
                pass
            self.clean_notification(nid)
            if self.closed_cb:
                self.closed_cb(nid, int(reason), reason_str)

    def ActionInvoked(self, actual_id, action):
        nid = self._find_nid(actual_id)
        log("ActionInvoked(%s, %s) nid=%s", actual_id, action, nid)
        if nid:
            if self.action_cb:
                self.action_cb(nid, str(action))

    def NotifyError(self, dbus_error, *_args):
        try:
            if type(dbus_error)==dbus.exceptions.DBusException:
                message = dbus_error.get_dbus_message()
                dbus_error_name = dbus_error.get_dbus_name()
                if dbus_error_name!="org.freedesktop.DBus.Error.ServiceUnknown":
                    log.error("unhandled dbus exception: %s, %s", message, dbus_error_name)
                    return False

                if not self.may_retry:
                    log.error("Error: cannot send notification via dbus,")
                    log.error(" check that you notification service is operating properly")
                    return False
                self.may_retry = False

                log.info("trying to re-connect to the notification service")
                #try to connect to the notification again (just once):
                self.setup_dbusnotify()
                #and retry:
                self.show_notify(*self.last_notification)
        except:
            pass
        log.error("Error processing notification:")
        log.error(" %s", dbus_error)
        return False

    def close_notify(self, nid):
        actual_id = self.actual_notification_id.get(nid)
        if actual_id is None:
            log("close_notify(%i) actual notification not found, already closed?", nid)
            return
        log("close_notify(%i) actual id=%s", nid, actual_id)
        def CloseNotificationReply():
            try:
                self.actual_notification_id.pop(nid)
            except KeyError:
                pass
        def CloseNotificationError(dbus_error, *_args):
            log.warn("Error: error closing notification:")
            log.warn(" %s", dbus_error)
        self.dbusnotify.CloseNotification(actual_id,
             reply_handler = CloseNotificationReply,
             error_handler = CloseNotificationError)
