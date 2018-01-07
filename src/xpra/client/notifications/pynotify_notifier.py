#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pynotify                 #@UnresolvedImport
from xpra.client.notifications.notifier_base import NotifierBase


class PyNotify_Notifier(NotifierBase):

    def show_notify(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, icon):
        if not self.dbus_check(dbus_id):
            return
        icon_string = self.get_icon_string(nid, app_icon, icon)
        if icon_string:
            #closed(nid) will take care of removing the temporary file
            #FIXME: register for the closed signal instead of using a timer
            from xpra.gtk_common.gobject_compat import import_glib
            import_glib().timeout_add(10*1000, self.clean_notification, nid)
        pynotify.init(app_name or "Xpra")
        n = pynotify.Notification(summary, body, icon_string)
        n.set_urgency(pynotify.URGENCY_LOW)
        n.set_timeout(expire_timeout)
        n.show()

    def close_notify(self, nid):
        pass


def main():
    import glib
    import gtk
    def show():
        n = PyNotify_Notifier()
        n.show_notify("", 0, "Test", 0, "", "Summary", "Body...", 0)
        return False
    glib.idle_add(show)
    glib.timeout_add(20000, gtk.main_quit)
    gtk.main()


if __name__ == "__main__":
    main()
