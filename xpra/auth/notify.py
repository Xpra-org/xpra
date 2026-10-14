# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Asks the current user(s) of the session to allow or deny the connection,
using a dbus notification with actions.
In shadow mode, the notification is shown on the desktop being shadowed.
In seamless mode, the notification service on the session bus is our own forwarder,
so the request is shown by the clients currently connected (if they have notifications enabled).
"""

import threading
from collections.abc import Sequence
from itertools import count

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import std
from xpra.util.thread import is_main_thread
from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.notification.dbus_backend import DBUSNotifier

GLib = gi_import("GLib")

TIMEOUT = 30
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


class Authenticator(SysAuthenticator):

    __slots__ = ("connection_str", "event", "nid", "notifier", "result", "timeout")

    def __init__(self, **kwargs):
        log(f"notify.Authenticator({kwargs})")
        self.timeout = int(kwargs.pop("timeout", TIMEOUT))
        connection = kwargs.get("connection")
        if not connection:
            raise ValueError("connection object is missing")
        self.connection_str = str(connection)
        super().__init__(**kwargs)
        self.event = threading.Event()
        self.result = False
        self.nid = 0
        self.notifier = None

    def requires_challenge(self) -> bool:
        return False

    def validate_caps(self, caps: typedict) -> bool:
        return True

    def default_authenticate_check(self, caps: typedict) -> bool:
        if is_main_thread():
            log.error("Error: notify authentication cannot run from the main thread")
            return False
        self.event.clear()
        self.result = False
        GLib.idle_add(self.show_request)
        if not self.event.wait(self.timeout):
            log.info("notify authentication request timed out after %i seconds", self.timeout)
            GLib.idle_add(self.close_request)
            return False
        log("notify authentication result=%s", self.result)
        return self.result

    def show_request(self) -> None:
        try:
            self.notifier = AuthNotifier(self.closed, self.action)
        except Exception as e:
            log("AuthNotifier()", exc_info=True)
            log.error("Error: notify authentication cannot access the notification service")
            log.estr(e)
            self.event.set()
            return
        if not self.notifier.handles_actions:
            log.error("Error: the notification service does not support actions,")
            log.error(" notify authentication cannot be used")
            self.close_request()
            self.event.set()
            return
        self.nid = next(nid_counter)
        summary = "Connection request"
        body = f"from {self.connection_str}"
        if self.username:
            body += f"\nas user {std(self.username)!r}"
        actions = (ALLOW, "Allow", DENY, "Deny")
        hints = {"urgency": URGENCY_CRITICAL}
        log("show_request() nid=%i, body=%r", self.nid, body)
        self.notifier.show_notify("", None, self.nid, "Xpra", 0, "",
                                  summary, body, actions, hints, self.timeout * 1000, None)

    def action(self, nid: int, action: str) -> None:
        log("action(%i, %r) expected nid=%i", nid, action, self.nid)
        if nid != self.nid:
            return
        self.result = action == ALLOW
        self.nid = 0
        self.event.set()
        GLib.idle_add(self.close_request)

    def closed(self, nid: int, reason: int, reason_str: str) -> None:
        log("closed(%i, %i, %r) expected nid=%i", nid, reason, reason_str, self.nid)
        if nid != self.nid:
            return
        self.nid = 0
        self.event.set()
        GLib.idle_add(self.close_request)

    def close_request(self) -> None:
        notifier = self.notifier
        log("close_request() notifier=%s, nid=%i", notifier, self.nid)
        if not notifier:
            return
        self.notifier = None
        self.nid = 0
        # closes the request if it is still showing:
        notifier.cleanup()

    def cleanup(self) -> None:
        if is_main_thread():
            self.close_request()
        else:
            GLib.idle_add(self.close_request)

    def __repr__(self):
        return "notify"
