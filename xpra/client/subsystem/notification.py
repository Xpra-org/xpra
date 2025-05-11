# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any
from collections.abc import Sequence, Callable

from xpra.os_util import gi_import
from xpra.common import NotificationID, noop, BACKWARDS_COMPATIBLE
from xpra.platform.paths import get_icon_filename
from xpra.platform.notification import get_backends
from xpra.net.common import Packet
from xpra.util.objects import typedict, make_instance
from xpra.util.str_fn import repr_ellipsized
from xpra.util.env import envbool
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("notify")

NATIVE_NOTIFIER = envbool("XPRA_NATIVE_NOTIFIER", True)
THREADED_NOTIFICATIONS = envbool("XPRA_THREADED_NOTIFICATIONS", True)


class NotificationClient(StubClientMixin):
    """
    Mixin for clients that handle notifications
    """
    PREFIX = "notification"

    def __init__(self):
        self.client_supports_notifications = False
        self.server_notifications = False
        self.notifications_enabled = False
        self.notifier = None
        self.tray = None
        self.notification_callbacks: dict[int, Callable] = {}
        # override the default handler in client base:
        self.may_notify = self.do_notify

    def init(self, opts) -> None:
        if opts.notifications:
            try:
                from xpra import notification
                assert notification
            except ImportError:
                log.warn("Warning: notification module not found")
            else:
                self.client_supports_notifications = True
                self.notifier = self.make_notifier()
                log("using notifier=%s", self.notifier)
                self.client_supports_notifications = self.notifier is not None

    def cleanup(self) -> None:
        n = self.notifier
        log("NotificationClient.cleanup() notifier=%s", n)
        if n:
            self.notifier = None
            with log.trap_error(f"Error on notifier {n!r} cleanup"):
                n.cleanup()

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_notifications = "notifications" in c
        self.notifications_enabled = self.client_supports_notifications
        return True

    def get_caps(self) -> dict[str, Any]:
        enabled = self.client_supports_notifications
        caps: dict[str, Any] = {
            NotificationClient.PREFIX: enabled,
        }
        if BACKWARDS_COMPATIBLE:
            caps["notifications"] = {
                "enabled": enabled,
            }
        return caps

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(f"{NotificationClient.PREFIX}-show", f"{NotificationClient.PREFIX}-close")
        self.add_legacy_alias("notify_show", f"{NotificationClient.PREFIX}-show")
        self.add_legacy_alias("notify_close", f"{NotificationClient.PREFIX}-close")

    def make_notifier(self):
        nc = self.get_notifier_classes()
        log("make_notifier() notifier classes: %s", nc)
        return make_instance(nc, self.notification_closed, self.notification_action)

    def notification_closed(self, nid: int, reason=3, text="") -> None:
        log("notification_closed(%i, %i, %s)", nid, reason, text)
        callback = self.notification_callbacks.pop(nid, None)
        if callback:
            callback("notification-close", nid, reason, text)
        else:
            self.send("notification-close", nid, reason, text)

    def notification_action(self, nid: int, action_id: str) -> None:
        log("notification_action(%i, %s)", nid, action_id)
        callback = self.notification_callbacks.get(nid, None)
        if callback:
            callback("notification-action", nid, action_id)
        else:
            self.send("notification-action", nid, action_id)

    def get_notifier_classes(self) -> Sequence[Callable]:
        # subclasses will generally add their toolkit specific variants
        # by overriding this method
        # use the native ones first:
        if not NATIVE_NOTIFIER:
            return ()
        return get_backends()

    def do_notify(self, nid: int | NotificationID, summary: str, body: str, actions: Sequence[str] = (),
                  hints: dict | None = None, expire_timeout=10 * 1000, icon_name: str = "", callback=noop) -> None:
        log("do_notify%s client_supports_notifications=%s, notifier=%s",
            (nid, summary, body, actions, hints, expire_timeout, icon_name),
            self.client_supports_notifications, self.notifier)
        if callback:
            self.notification_callbacks[nid] = callback
        n = self.notifier
        if not self.client_supports_notifications or not n:
            # just log it instead:
            log.info("%s", summary)
            if body:
                for x in body.splitlines():
                    log.info(" %s", x)
            return

        def show_notification() -> None:
            try:
                from xpra.notification.common import parse_image_path
                icon_filename = get_icon_filename(icon_name)
                icon = parse_image_path(icon_filename)
                n.show_notify("", self.tray, int(nid), "Xpra", int(nid), "",
                              summary, body, actions, hints or {}, expire_timeout, icon)
            except Exception as e:
                log("failed to show notification", exc_info=True)
                log.error("Error: cannot show notification")
                log.error(" '%s'", summary)
                log.estr(e)

        if THREADED_NOTIFICATIONS:
            show_notification()
        else:
            GLib.idle_add(show_notification)

    def _process_notification_show(self, packet: Packet) -> None:
        if not self.notifications_enabled:
            log("process_notify_show: ignoring packet, notifications are disabled")
            return
        self._ui_event()
        dbus_id = packet.get_str(1)
        nid = packet.get_u64(2)
        app_name = packet.get_str(3)
        replaces_nid = packet.get_u64(4)
        app_icon = packet.get_str(5)
        summary = packet.get_str(6)
        body = packet.get_str(7)
        expire_timeout = packet.get_i64(8)
        icon = None
        actions: Sequence[str] = ()
        hints = {}
        if len(packet) >= 10:
            icon = packet[9]
        if len(packet) >= 12:
            actions = packet.get_strs(10)
            hints = packet.get_dict(11)
        # note: if the server doesn't support notification forwarding,
        # it can still send us the messages (via xpra control or the dbus interface)
        log("_process_notification_show(%s) notifier=%s, server_notifications=%s",
            repr_ellipsized(packet), self.notifier, self.server_notifications)
        log("notification actions=%s, hints=%s", actions, hints)
        assert self.notifier
        # this one of the few places where we actually do care about character encoding:
        tray = self.get_tray_window(app_name, hints)
        log("get_tray_window(%s)=%s", app_name, tray)
        self.notifier.show_notify(dbus_id, tray, nid,
                                  app_name, replaces_nid, app_icon,
                                  summary, body, actions, hints, expire_timeout, icon)

    def _process_notification_close(self, packet: Packet) -> None:
        if not self.notifications_enabled:
            return
        assert self.notifier
        nid = packet.get_u64(1)
        log("_process_notification_close(%s)", nid)
        self.notifier.close_notify(nid)

    def get_tray_window(self, _app_name, _hints):
        # overridden in subclass to use the correct window if we can find it
        return self.tray
