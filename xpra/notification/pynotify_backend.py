#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any
import notify2

from xpra.common import noop
from xpra.notification.base import NotifierBase, NID


def close_notify(nid: NID) -> None:
    n = PyNotifyNotifier.CACHE.pop(int(nid), None)
    if n:
        n.close()


class PyNotifyNotifier(NotifierBase):
    CACHE: dict[int, Any] = {}

    def __init__(self, closed_cb=noop, action_cb=noop):
        super().__init__(closed_cb, action_cb)
        if not notify2.is_initted():
            notify2.init("Xpra", "glib")

    def show_notify(self, dbus_id: str, tray, nid: NID,
                    app_name: str, replaces_nid: NID, app_icon: str,
                    summary: str, body: str, actions, hints, timeout: int, icon) -> None:
        if not self.dbus_check(dbus_id):
            return
        icon_string = self.get_icon_string(nid, app_icon, icon)
        n = notify2.Notification(summary, body, icon_string)
        PyNotifyNotifier.CACHE[int(nid)] = n
        n.set_urgency(notify2.URGENCY_LOW)
        n.set_timeout(timeout)
        n.show()
        if icon_string:
            def notification_closed(*_args):
                self.clean_notification(int(nid))

            n.connect("closed", notification_closed)

    def clean_notification(self, nid: int) -> None:
        PyNotifyNotifier.CACHE.pop(nid, None)
        super().clean_notification(nid)


def main(args):
    from xpra.os_util import gi_import
    Gtk = gi_import("Gtk")
    GLib = gi_import("GLib")
    summary = "Summary"
    body = "Body..."
    if len(args) > 1:
        summary = args[1]
    if len(args) > 2:
        body = args[2]

    def show() -> bool:
        nid = 1
        n = PyNotifyNotifier()
        n.show_notify("", None, nid, "Test", 0, "", summary, body, ["0", "Hello", "1", "Bye"], {}, 0, "")
        GLib.timeout_add(5000, close_notify, nid)
        return False

    GLib.idle_add(show)
    GLib.timeout_add(20000, Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main(sys.argv)
