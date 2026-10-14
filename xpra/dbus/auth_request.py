# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
`notify` authentication backend using a dbus notification with "Allow" and "Deny" actions.
In shadow mode, the notification is shown on the desktop being shadowed.
In seamless mode, the notification service on the session bus is our own forwarder,
so the request is shown by the clients currently connected (if they have notifications enabled).
"""

from collections.abc import Callable, Sequence
from itertools import count

from xpra.notification.dbus_backend import DBUSNotifier
from xpra.log import Logger

log = Logger("auth", "notify")

ALLOW = "allow"
DENY = "deny"
URGENCY_CRITICAL = 2

nid_counter = count(1)


class AuthNotifier(DBUSNotifier):
    """
    The regular dbus notifier refuses to forward notifications to xpra's own notification forwarder,
    because this would loop when forwarding client notifications.
    Here, forwarding the request to the connected clients is exactly what we want.
    """

    def loop_check(self, server_info: Sequence[str]) -> None:
        """ the xpra notification forwarder is a valid target """

    def dbus_check(self, dbus_id: str) -> bool:
        return True


class DBusRequest:
    """ must be created and closed from the main thread """

    def __init__(self, summary: str, body: str, timeout: int, callback: Callable[[bool], None]):
        self.callback = callback
        self.notifier = AuthNotifier(self.closed, self.action)
        if not self.notifier.handles_actions:
            self.close()
            raise RuntimeError("the notification service does not support actions")
        self.nid = next(nid_counter)
        actions = (ALLOW, "Allow", DENY, "Deny")
        hints = {"urgency": URGENCY_CRITICAL}
        log("DBusRequest nid=%i, body=%r", self.nid, body)
        self.notifier.show_notify("", None, self.nid, "Xpra", 0, "",
                                  summary, body, actions, hints, timeout * 1000, None)

    def action(self, nid: int, action: str) -> None:
        log("action(%i, %r) expected nid=%i", nid, action, self.nid)
        if nid != self.nid:
            return
        self.nid = 0
        self.callback(action == ALLOW)

    def closed(self, nid: int, reason: int, reason_str: str) -> None:
        log("closed(%i, %i, %r) expected nid=%i", nid, reason, reason_str, self.nid)
        if nid != self.nid:
            return
        self.nid = 0
        self.callback(False)

    def close(self) -> None:
        notifier = self.notifier
        log("close() notifier=%s, nid=%i", notifier, getattr(self, "nid", 0))
        if notifier:
            self.notifier = None
            # closes the request if it is still showing:
            notifier.cleanup()
