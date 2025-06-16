# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Sequence

from xpra.util.env import first_time
from xpra.util.str_fn import csv, Ellipsizer, bytestostr
from xpra.os_util import gi_import
from xpra.dbus.helper import native_to_dbus
from xpra.notification.base import NotifierBase, log, NID
import dbus
from dbus.mainloop.glib import DBusGMainLoop, threads_init
from dbus.exceptions import DBusException

threads_init()
DBusGMainLoop(set_as_default=True)

NOTIFICATION_APP_NAME = os.environ.get("XPRA_NOTIFICATION_APP_NAME", "%s (via Xpra)")
FD_NOTIFICATIONS = "org.freedesktop.Notifications"


class DBUSNotifier(NotifierBase):

    def __init__(self, *args):
        super().__init__(*args)
        self.app_name_format = NOTIFICATION_APP_NAME
        self.last_notification: Sequence[Any] = ()
        self.actual_notification_id: dict[int, int] = {}
        self.dbus_session = dbus.SessionBus()
        self.dbusnotify = self.setup_dbusnotify()
        self.handles_actions = "actions" in self.get_capabilities()
        self.may_retry = True
        log("dbus.get_default_main_loop()=%s", dbus.get_default_main_loop())

    def setup_dbusnotify(self) -> dbus.Interface:
        self.org_fd_notifications = self.dbus_session.get_object(FD_NOTIFICATIONS, '/org/freedesktop/Notifications')
        self.org_fd_notifications.connect_to_signal("NotificationClosed", self.NotificationClosed)
        self.org_fd_notifications.connect_to_signal("ActionInvoked", self.ActionInvoked)

        # connect_to_signal("HelloSignal", hello_signal_handler, dbus_interface="com.example.TestService", arg0="Hello")
        dbusnotify = dbus.Interface(self.org_fd_notifications, FD_NOTIFICATIONS)
        log("using dbusnotify: %s(%s)", type(dbusnotify), FD_NOTIFICATIONS)
        return dbusnotify

    def get_capabilities(self) -> Sequence[str]:
        caps = tuple(str(x) for x in self.dbusnotify.GetCapabilities())
        log("capabilities=%s", csv(caps))
        return caps

    def cleanup(self) -> None:
        nids = list(self.actual_notification_id.items())
        self.actual_notification_id = {}
        for nid, actual_id in nids:
            self.do_close(nid, actual_id)
        super().cleanup()
        self.dbusnotify = None

    def show_notify(self, dbus_id: str, tray, nid: NID,
                    app_name: str, replaces_nid: NID, app_icon: str,
                    summary: str, body: str, actions, hints: dict, timeout: int, icon) -> None:
        if not self.dbus_check(dbus_id):
            return
        if not self.dbusnotify:
            return
        self.may_retry = True
        with log.trap_error("Error: dbus notify failed"):
            icon_string = self.get_icon_string(nid, app_icon, icon)
            log("get_icon_string%s=%s", (nid, app_icon, Ellipsizer(icon)), icon_string)
            if app_name == "Xpra":
                # don't show "Xpra (via Xpra)"
                app_str = "Xpra"
            else:
                try:
                    app_str = self.app_name_format % app_name
                except TypeError:
                    app_str = app_name or "Xpra"
            self.last_notification = (
                dbus_id, tray, nid, app_name, replaces_nid,
                app_icon, summary, body, actions, hints, timeout, icon,
            )

            def NotifyReply(notification_id) -> None:
                log("NotifyReply(%s) for nid=%i", notification_id, nid)
                self.actual_notification_id[int(nid)] = int(notification_id)

            def NotifyError(dbus_error, *args) -> bool:
                log("NotifyError(%s, %s) for nid=%i", dbus_error, args, nid)
                return self.NotifyError(nid, dbus_error)

            dbus_hints = self.parse_hints(hints)
            log("calling %s%s", self.dbusnotify.Notify,
                (app_str, 0, icon_string, summary, body, actions, dbus_hints, timeout))
            self.dbusnotify.Notify(app_str, 0, icon_string, summary, body, actions, dbus_hints, timeout,
                                   reply_handler=NotifyReply,
                                   error_handler=NotifyError)

    def _find_nid(self, actual_id) -> int:
        aid = int(actual_id)
        for k, v in self.actual_notification_id.items():
            if v == aid:
                return k
        return 0

    def noparse_hints(self, h) -> dict:
        return h

    def parse_hints(self, h) -> dbus.types.Dictionary:
        hints = {}
        for x in ("action-icons", "category", "desktop-entry", "resident", "transient", "x", "y", "urgency"):
            v = h.get(x)
            if v is not None:
                hints[native_to_dbus(x)] = native_to_dbus(v)
        image_data = h.get("image-data")
        if image_data and bytestostr(image_data[0]) == "png":
            try:
                from xpra.codecs.pillow.decoder import open_only  # pylint: disable=import-outside-toplevel
                img_data = image_data[3]
                img = open_only(img_data, ("png",))
                w, h = img.size
                channels = len(img.mode)
                rowstride = w * channels
                has_alpha = img.mode == "RGBA"
                pixel_data = bytearray(img.tobytes("raw", img.mode))
                args = w, h, rowstride, has_alpha, 8, channels, pixel_data
                hints["image-data"] = tuple(native_to_dbus(x) for x in args)
            except Exception as e:
                log("parse_hints(%s) error on image-data=%s", h, image_data, exc_info=True)
                log.error("Error parsing notification image:")
                log.estr(e)
        log("parse_hints(%s)=%s", h, hints)
        return dbus.types.Dictionary(hints, signature="sv")

    def NotificationClosed(self, actual_id: dbus.UInt32, reason) -> None:
        nid = self._find_nid(actual_id)
        reason_str = {
            1: "expired",
            2: "dismissed by the user",
            3: "closed by a call to CloseNotification",
            4: "Undefined/reserved reasons",
        }.get(int(reason), str(reason))
        log("NotificationClosed(%s, %s) nid=%s, reason=%s", actual_id, reason, nid, reason_str)
        if nid:
            self.actual_notification_id.pop(nid, None)
            self.clean_notification(nid)
            if self.closed_cb:
                self.closed_cb(nid, int(reason), reason_str)

    def ActionInvoked(self, actual_id: dbus.UInt32, action) -> None:
        nid = self._find_nid(actual_id)
        log("ActionInvoked(%s, %s) nid=%s", actual_id, action, nid)
        if nid and self.action_cb:
            self.action_cb(nid, str(action))
        self.clean_notification(nid)

    def NotifyError(self, nid: NID, dbus_error) -> bool:
        if not self.dbusnotify:
            return False
        try:
            if isinstance(dbus_error, DBusException):
                message = dbus_error.get_dbus_message()
                dbus_error_name = dbus_error.get_dbus_name()
                if dbus_error_name != "org.freedesktop.DBus.Error.ServiceUnknown":
                    log.error("unhandled dbus exception: %s, %s", message, dbus_error_name)
                    self.clean_notification(nid)
                    return False

                if not self.may_retry:
                    log.error("Error: cannot send notification via dbus,")
                    log.error(" check that you notification service is operating properly")
                    self.clean_notification(nid)
                    return False
                self.may_retry = False

                log.info("trying to re-connect to the notification service")
                # try to connect to the notification again (just once):
                self.setup_dbusnotify()
                # and retry:
                self.show_notify(*self.last_notification)
        except Exception:
            log("cannot filter error", exc_info=True)
        log.error("Error processing notification:")
        log.estr(dbus_error)
        self.clean_notification(nid)
        return False

    def close_notify(self, nid: NID) -> None:
        actual_id = self.actual_notification_id.get(int(nid))
        if actual_id is None:
            log("close_notify(%i) actual notification not found, already closed?", nid)
            return
        log("close_notify(%i) actual id=%s", nid, actual_id)
        self.do_close(nid, actual_id)

    def do_close(self, nid: NID, actual_id: int) -> None:
        log("do_close_notify(%i)", actual_id)
        if not self.dbusnotify:
            return

        def CloseNotificationReply() -> None:
            self.actual_notification_id.pop(actual_id, None)
            self.clean_notification(nid)

        def CloseNotificationError(dbus_error, *_args) -> None:
            if first_time(f"close-notification-{actual_id}"):
                log.warn("Error: error closing notification:")
                log.warn(" %s", dbus_error)
            self.clean_notification(nid)

        self.dbusnotify.CloseNotification(actual_id,
                                          reply_handler=CloseNotificationReply,
                                          error_handler=CloseNotificationError)


def DBUS_Notifier_factory(*args) -> DBUSNotifier | None:
    try:
        return DBUSNotifier(*args)
    except Exception as e:
        log.warn("Warning: failed to instantiate the dbus notification handler")
        if str(e).startswith("org.freedesktop.DBus.Error.ServiceUnknown:"):
            log.warn(f" you may need to start a notification service for {FD_NOTIFICATIONS!r}")
        else:
            log.warn(" %s", e)
        log.warn(" disable notification to avoid this warning")
        return None


def main():
    # pylint: disable=import-outside-toplevel
    Gtk = gi_import("Gtk")
    GLib = gi_import("GLib")

    def show() -> bool:
        n = DBUS_Notifier_factory()
        # actions = ["0", "Hello", "1", "Bye"]
        actions = ()
        n.show_notify("", None, 0, "Test", 0, "",
                      "Summary", "Body line1\nline2...",
                      actions, {}, 0, "")
        return False

    GLib.idle_add(show)
    GLib.timeout_add(20000, Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
