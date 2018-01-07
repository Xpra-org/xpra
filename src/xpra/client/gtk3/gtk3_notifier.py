# This file is part of Xpra.
# Copyright (C) 2011-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import Notify            #@UnresolvedImport
from xpra.client.notifications.notifier_base import NotifierBase

from xpra.log import Logger
log = Logger("notify")


class GTK3_Notifier(NotifierBase):

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, icon):
        if not self.dbus_check(dbus_id):
            return
        icon_string = self.get_icon_string(nid, app_icon, icon)
        Notify.init(app_name or "Xpra")
        n = Notify.Notification.new(summary, body, icon_string)
        n.connect("closed", self.closed, nid)
        n.show()


    def close_notify(self, nid):
        self.closed(None, nid)
