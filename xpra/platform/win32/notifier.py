# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from collections.abc import Sequence

from xpra.util.env import envbool
from xpra.notification.base import NotifierBase, log, NID
from xpra.platform.win32.balloon import notify

GTK_NOTIFIER = envbool("XPRA_WIN32_GTK_NOTIFIER", False)
if GTK_NOTIFIER:
    try:
        from xpra.gtk.notifier import GTKNotifier
    except ImportError:
        GTK_NOTIFIER = False


def do_notify(*args):
    # if GLib is loaded, use it to ensure we use the UI thread:
    GLib = sys.modules.get("gi.repository.GLib", None)
    if GLib:
        GLib.idle_add(notify, *args)
    else:
        notify(*args)


class Win32_Notifier(NotifierBase):

    def __init__(self, *args):
        super().__init__(*args)
        self.handles_actions = GTK_NOTIFIER
        self.gtk_notifier = None
        self.gtk_notifications = set()
        self.notification_handles = {}

    def get_gtk_notifier(self):
        if self.gtk_notifier is None and GTK_NOTIFIER:
            try:
                self.gtk_notifier = GTKNotifier(self.closed_cb, self.action_cb)
            except Exception:
                log("failed to load GTK Notifier fallback", exc_info=True)
        return self.gtk_notifier

    def show_notify(self, dbus_id: str, tray, nid: NID,
                    app_name: str, replaces_nid: NID,
                    app_icon: str, summary: str, body: str,
                    actions: Sequence[str], hints: dict, expire_timeout: int, icon):
        if not tray:
            log.warn("Warning: cannot show notifications without a system tray")
            return
        getHWND = getattr(tray, "getHWND", None)
        if GTK_NOTIFIER and (actions or not getHWND):
            log("show_notify(..) using gtk fallback, GTK_NOTIFIER=%s, tray=%s, getHWND=%s, actions=%s",
                GTK_NOTIFIER, tray, getHWND, actions)
            gtk_notifier = self.get_gtk_notifier()
            if gtk_notifier:
                gtk_notifier.show_notify(dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, actions,
                                         hints, expire_timeout, icon)
                self.gtk_notifications.add(nid)
                return
        if not getHWND:
            log.warn(f"Warning: missing 'getHWND' on {tray} ({type(tray)}")
            return
        if tray is None:
            log.warn("Warning: no system tray - cannot show notification!")
            return
        hwnd = getHWND()
        app_id = tray.app_id
        log("show_notify%s hwnd=%#x, app_id=%i",
            (dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon),
            hwnd, app_id)
        # FIXME: remove handles when notification is closed
        self.notification_handles[int(nid)] = (hwnd, app_id)
        do_notify(hwnd, app_id, summary, body, expire_timeout, icon)

    def close_notify(self, nid: NID):
        try:
            self.gtk_notifications.remove(int(nid))
            if self.gtk_notifier:
                self.gtk_notifier.close_notify(nid)
        except KeyError:
            try:
                hwnd, app_id = self.notification_handles.pop(int(nid))
            except KeyError:
                return
            log("close_notify(%i) hwnd=%i, app_id=%i", nid, hwnd, app_id)
            do_notify(hwnd, app_id, "", "", 0, None)
