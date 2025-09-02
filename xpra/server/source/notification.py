# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence, Callable

from xpra.util.objects import typedict
from xpra.common import NotificationID, BACKWARDS_COMPATIBLE
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("notify")


class NotificationConnection(StubClientConnection):

    PREFIX = "notification"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        if caps.boolget("notification"):
            return True
        if BACKWARDS_COMPATIBLE:
            v = caps.get("notifications")
            if isinstance(v, bool):
                return v
            if isinstance(v, dict):
                return typedict(v).boolget("enabled", False)
        return False

    def init_state(self) -> None:
        self.send_notifications: bool = False
        self.notification_callbacks: dict[int, Callable] = {}
        self.hello_sent = 0.0

    def parse_client_caps(self, c: typedict) -> None:
        if not BACKWARDS_COMPATIBLE:
            self.send_notifications = c.boolget("notification")
        else:
            v = c.get("notifications")
            if isinstance(v, dict):
                self.send_notifications = typedict(v).boolget("enabled")
        log("parse_client_caps(..) notification=%s", self.send_notifications)

    def get_info(self) -> dict[str, Any]:
        return {
            NotificationConnection.PREFIX: self.send_notifications,
        }

    ######################################################################
    # notifications:
    # Utility functions for subsystem (makes notifications optional)
    def may_notify(self, nid: int | NotificationID = 0, summary: str = "", body: str = "",
                   actions=(), hints: dict | None = None, expire_timeout=10 * 1000,
                   icon_name: str = "", user_callback: Callable | None = None) -> None:
        try:
            from xpra.platform.paths import get_icon_filename
            from xpra.notification.common import parse_image_path
        except ImportError as e:
            log("not sending notification: %s", e)
        else:
            icon_filename = get_icon_filename(icon_name)
            icon = parse_image_path(icon_filename)
            self.notify("", int(nid), "Xpra", 0, "",
                        summary, body, actions, hints or {},
                        expire_timeout, icon, user_callback)

    def notify(self, dbus_id: str, nid: int, app_name: str, replaces_nid: int, app_icon: str,
               summary: str, body: str,
               actions: Sequence[str], hints: dict, expire_timeout: int,
               icon, user_callback: Callable | None = None) -> bool:
        args = (dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon)
        log("notify%s types=%s", args, tuple(type(x) for x in args))
        if not self.send_notifications:
            log("client %s does not support notifications", self)
            return False
        # "suspended" belongs in the WindowsMixin:
        if getattr(self, "suspended", False):
            log("client %s is suspended, notification not sent", self)
            return False
        if user_callback:
            self.notification_callbacks[nid] = user_callback
        packet_type = "notify_show" if BACKWARDS_COMPATIBLE else "notification-show"
        if self.hello_sent:
            # Warning: actions and hints are send last because they were added later (in version 2.3)
            self.send_async(packet_type, dbus_id, nid, app_name, replaces_nid, app_icon,
                            summary, body, expire_timeout, icon or b"", tuple(actions), hints)
        return True

    def notify_close(self, nid: int) -> None:
        if not self.send_notifications or self.suspended or not self.hello_sent:
            return
        packet_type = "notify_close" if BACKWARDS_COMPATIBLE else "notification-close"
        self.send_more(packet_type, nid)
