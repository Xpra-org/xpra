#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pynotify                 #@UnresolvedImport

from xpra.notifications.notifier_base import NotifierBase


class PyNotify_Notifier(NotifierBase):

    def show_notify(self, dbus_id, _tray, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon):
        if not self.dbus_check(dbus_id):
            return
        icon_string = self.get_icon_string(nid, app_icon, icon)
        pynotify.init(app_name or "Xpra")
        n = pynotify.Notification(summary, body, icon_string)
        n.set_urgency(pynotify.URGENCY_LOW)
        n.set_timeout(expire_timeout)
        if actions and False:
            while len(actions)>=2:
                action_id, action_label = actions[:2]
                self.add_action(n, action_id, action_label)
                actions = actions[2:]
        n.show()
        if icon_string:
            def notification_closed(*_args):
                self.clean_notification(nid)
            n.connect("closed", notification_closed)

    def add_action(self, n, action_id, action_label):
        #n.add_action("foo", "Foo!", foo_action)
        def callback(*_args):
            pass
        n.add_action(action_id, action_label, callback)

    def close_notify(self, nid):
        pass


def main():
    from xpra.gtk_common.gobject_compat import import_glib, import_gtk
    glib = import_glib()
    gtk = import_gtk()
    def show():
        n = PyNotify_Notifier()
        n.show_notify("", None, 0, "Test", 0, "", "Summary", "Body...", ["0", "Hello", "1", "Bye"], {}, 0, "")
        return False
    glib.idle_add(show)
    glib.timeout_add(20000, gtk.main_quit)
    gtk.main()


if __name__ == "__main__":
    main()
