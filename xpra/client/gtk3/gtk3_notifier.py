# This file is part of Xpra.
# Copyright (C) 2011-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position

import gi
gi.require_version('Notify', '0.7')  # @UndefinedVariable
from gi.repository import Notify            #@UnresolvedImport

from xpra.notifications.notifier_base import NotifierBase


class GTK3_Notifier(NotifierBase):

    def show_notify(self, dbus_id, tray, nid:int,
                    app_name:str, replaces_nid:int, app_icon,
                    summary:str, body:str, actions, hints, timeout:int, icon):
        if not self.dbus_check(dbus_id):
            return
        icon_string = self.get_icon_string(nid, app_icon, icon)
        Notify.init(app_name or "Xpra")
        n = Notify.Notification.new(summary=summary, body=body, icon=icon_string)
        def closed(*_args):
            self.clean_notification(nid)
        n.connect("closed", closed)
        n.show()


    def close_notify(self, nid:int) -> None:
        self.clean_notification(nid)

    def cleanup(self) -> None:
        Notify.uninit()
        super().cleanup()
