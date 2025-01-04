# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.notifications.notifier_base import NotifierBase, NID

Notify = gi_import("Notify")


class GINotifier(NotifierBase):

    def show_notify(self, dbus_id, tray, nid: NID,
                    app_name: str, replaces_nid: NID, app_icon,
                    summary: str, body: str, actions, hints, timeout: int, icon) -> None:
        if not self.dbus_check(dbus_id):
            return
        icon_string = self.get_icon_string(nid, app_icon, icon)
        Notify.init(app_name or "Xpra")
        n = Notify.Notification.new(summary=summary, body=body, icon=icon_string)

        def closed(*_args) -> None:
            self.clean_notification(nid)

        n.connect("closed", closed)
        n.show()

    def close_notify(self, nid: NID) -> None:
        self.clean_notification(nid)

    def cleanup(self) -> None:
        Notify.uninit()
        super().cleanup()
