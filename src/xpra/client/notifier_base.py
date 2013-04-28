# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger()


class NotifierBase(object):

    def __init__(self):
        self.has_dbusnotify = False
        self.has_pynotify = False
        if not self.setup_dbusnotify() and not self.setup_pynotify():
            log.error("turning notifications off")


    def setup_dbusnotify(self):
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        try:
            import dbus.glib
            assert dbus.glib
            self.dbus_session = dbus.SessionBus()
            FD_NOTIFICATIONS = 'org.freedesktop.Notifications'
            self.org_fd_notifications = self.dbus_session.get_object(FD_NOTIFICATIONS, '/org/freedesktop/Notifications')
            self.dbusnotify = dbus.Interface(self.org_fd_notifications, FD_NOTIFICATIONS)
            self.has_dbusnotify = True
            log("using dbusnotify: %s(%s)", type(self.dbusnotify), FD_NOTIFICATIONS)
        except Exception, e:
            log("cannot import dbus.glib notification wrapper: %s", e)
            log.error("failed to locate the dbus notification service")
        return self.has_dbusnotify

    def setup_pynotify(self):
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        try:
            import pynotify
            pynotify.init("Xpra")
            self.has_pynotify = True
            log("using pynotify: %s", pynotify)
        except ImportError, e:
            log.error("cannot import pynotify wrapper: %s", e)
        return self.has_pynotify



    def can_notify(self):
        return  self.has_dbusnotify or self.has_pynotify

    def show_notify(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, may_retry=True):
        if self.dbus_id==dbus_id:
            log.error("remote dbus instance is the same as our local one, "
                      "cannot forward notification to ourself as this would create a loop")
            return
        if self.has_dbusnotify:
            def cbReply(*args):
                log("notification reply: %s", args)
                return False
            def cbError(dbus_error, *args):
                try:
                    import dbus.exceptions
                    if type(dbus_error)==dbus.exceptions.DBusException:
                        message = dbus_error.get_dbus_message()
                        dbus_error_name = dbus_error.get_dbus_name()
                        if dbus_error_name!="org.freedesktop.DBus.Error.ServiceUnknown":
                            log.error("unhandled dbus exception: %s, %s", message, dbus_error_name)
                            return False

                        if not may_retry:
                            log.error("cannot send notification via dbus, please check that you notification service is operating properly")
                            return False

                        log.info("trying to re-connect to the notification service")
                        #try to connect to the notification again (just once):
                        if self.setup_dbusnotify():
                            self.show_notify(dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, may_retry=False)
                        return False
                except:
                    pass
                log.error("notification error: %s", dbus_error)
                return False
            try:
                self.dbusnotify.Notify("Xpra", 0, app_icon, summary, body, [], [], expire_timeout,
                     reply_handler = cbReply,
                     error_handler = cbError)
            except:
                log.error("dbus notify failed", exc_info=True)
        elif self.has_pynotify:
            try:
                import pynotify
                n = pynotify.Notification(summary, body)
                n.set_urgency(pynotify.URGENCY_LOW)
                n.set_timeout(expire_timeout)
                n.show()
            except:
                log.error("pynotify failed", exc_info=True)
        else:
            log.error("notification cannot be displayed, no backend support!")

    def close_notify(self, nid):
        pass
