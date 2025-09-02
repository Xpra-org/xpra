# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.objects import typedict
from typing import Any
from collections.abc import Callable

from xpra.common import NotificationID
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("notify")


class NotificationMixin(StubSourceMixin):

    PREFIX = "notification"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
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
        v = c.get("notifications")
        if isinstance(v, dict):
            self.send_notifications = typedict(v).boolget("enabled")
        log("send notifications=%s", self.send_notifications)

    def get_info(self) -> dict[str, Any]:
        return {
            NotificationMixin.PREFIX: self.send_notifications,
        }

    ######################################################################
    # notifications:
    # Utility functions for mixins (makes notifications optional)
    def may_notify(self, nid: int | NotificationID = 0, summary: str = "", body: str = "",
                   actions=(), hints=None, expire_timeout=10 * 1000,
                   icon_name: str = "", user_callback: Callable | None = None) -> None:
        try:
            from xpra.platform.paths import get_icon_filename
            from xpra.notifications.common import parse_image_path
        except ImportError as e:
            log("not sending notification: %s", e)
        else:
            icon_filename = get_icon_filename(icon_name)
            icon = parse_image_path(icon_filename)
            self.notify("", int(nid), "Xpra", 0, "",
                        summary, body, actions, hints or {},
                        expire_timeout, icon, user_callback)

    def notify(self, dbus_id, nid: int, app_name: str, replaces_nid: int, app_icon,
               summary: str, body: str, actions, hints, expire_timeout: int,
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
        if self.hello_sent:
            # Warning: actions and hints are send last because they were added later (in version 2.3)
            self.send_async("notify_show", dbus_id, nid, app_name, replaces_nid, app_icon,
                            summary, body, expire_timeout, icon or b"", actions, hints)
        return True

    def notify_close(self, nid: int) -> None:
        if not self.send_notifications or self.suspended or not self.hello_sent:
            return
        self.send_more("notify_close", nid)
