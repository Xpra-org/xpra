# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.notifications.notifier_base import NotifierBase, log
#beware: this import has side-effects:
import dbus.glib
assert dbus.glib
import dbus.exceptions


def DBUS_Notifier_factory():
    try:
        return DBUS_Notifier()
    except Exception as e:
        log.warn("failed to instantiate the dbus notification handler:")
        if str(e).startswith("org.freedesktop.DBus.Error.ServiceUnknown:"):
            log.warn(" you may need to start a notification service for 'org.freedesktop.Notifications'")
        else:
            log.warn(" %s", e)
        log.warn(" disable notifications to avoid this warning")
        return None

class DBUS_Notifier(NotifierBase):

    def __init__(self):
        NotifierBase.__init__(self)
        self.last_notification = None
        self.setup_dbusnotify()

    def setup_dbusnotify(self):
        self.dbus_session = dbus.SessionBus()
        FD_NOTIFICATIONS = 'org.freedesktop.Notifications'
        self.org_fd_notifications = self.dbus_session.get_object(FD_NOTIFICATIONS, '/org/freedesktop/Notifications')
        self.dbusnotify = dbus.Interface(self.org_fd_notifications, FD_NOTIFICATIONS)
        log("using dbusnotify: %s(%s)", type(self.dbusnotify), FD_NOTIFICATIONS)

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        if not self.dbus_check(dbus_id):
            return
        self.may_retry = True
        try:
            self.last_notification = (dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout)
            self.dbusnotify.Notify(app_name or "Xpra", 0, app_icon, summary, body, [], [], expire_timeout,
                 reply_handler = self.cbReply,
                 error_handler = self.cbError)
        except:
            log.error("dbus notify failed", exc_info=True)

    def cbReply(self, *args):
        log("notification reply: %s", args)
        return False

    def cbError(self, dbus_error, *_args):
        try:
            if type(dbus_error)==dbus.exceptions.DBusException:
                message = dbus_error.get_dbus_message()
                dbus_error_name = dbus_error.get_dbus_name()
                if dbus_error_name!="org.freedesktop.DBus.Error.ServiceUnknown":
                    log.error("unhandled dbus exception: %s, %s", message, dbus_error_name)
                    return False

                if not self.may_retry:
                    log.error("cannot send notification via dbus, please check that you notification service is operating properly")
                    return False
                self.may_retry = False

                log.info("trying to re-connect to the notification service")
                #try to connect to the notification again (just once):
                self.setup_dbusnotify()
                #and retry:
                self.show_notify(*self.last_notification)
        except:
            pass
        log.error("notification error: %s", dbus_error)
        return False

    def close_notify(self, nid):
        pass
