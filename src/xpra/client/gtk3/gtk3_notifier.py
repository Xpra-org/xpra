# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
assert "gtk" not in sys.modules
from gi.repository import Notify            #@UnresolvedImport
from xpra.client.notifications.notifier_base import NotifierBase


class GTK3_Notifier(NotifierBase):

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        if not self.dbus_check(dbus_id):
            return
        Notify.init(app_name or "Xpra")
        n = Notify.Notification.new(summary, body)
        n.show()

    def close_notify(self, nid):
        pass
