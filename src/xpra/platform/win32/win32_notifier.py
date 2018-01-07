# This file is part of Xpra.
# Copyright (C) 2011-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.notifications.notifier_base import NotifierBase, log
from xpra.platform.win32.win32_balloon import notify

class Win32_Notifier(NotifierBase):

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, icon):
        if tray is None:
            log.error("no tray - cannot show notification!")
            return
        if not hasattr(tray, "getHWND"):
            log.error("tray class %s does not support getHWND!", type(tray))
            return
        hwnd = tray.getHWND()
        notify(hwnd, summary, body, expire_timeout)

    def close_notify(self, nid):
        pass
