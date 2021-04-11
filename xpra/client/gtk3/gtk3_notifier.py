# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position

import gi
gi.require_version('Notify', '0.7')
from gi.repository import Notify            #@UnresolvedImport

from xpra.notifications.notifier_base import NotifierBase


class GTK3_Notifier(NotifierBase):

    def show_notify(self, dbus_id, tray, nid,
                    app_name, replaces_nid, app_icon,
                    summary, body, actions, hints, timeout, icon):
        if not self.dbus_check(dbus_id):
            return
        icon_string = self.get_icon_string(nid, app_icon, icon)
        Notify.init(app_name or "Xpra")
        n = Notify.Notification.new(summary, body, icon_string)
        def closed(*_args):
            self.clean_notification(nid)
        n.connect("closed", closed)
        n.show()


    def close_notify(self, nid):
        self.clean_notification(nid)
