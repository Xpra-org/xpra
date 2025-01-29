# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Any
from collections.abc import Callable, Sequence

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.env import envint
from xpra.common import NotificationID, ConnectionMessage
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("timeout")

GRACE_PERCENT = envint("XPRA_GRACE_PERCENT", 90)


class IdleMixin(StubSourceMixin):

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return caps.boolget("keyboard") or caps.boolget("mouse") or caps.boolget("windows")

    def __init__(self) -> None:
        self.idle_timeout = 0
        # duplicated from clientconnection:
        self.notification_callbacks: dict[int, Callable] = {}
        self.send_notifications = False
        self.send_notifications_actions = False

    def init_from(self, _protocol, server) -> None:
        self.idle_timeout = server.idle_timeout
        self.session_name = server.session_name

    def init_state(self) -> None:
        self.last_user_event = monotonic()
        # grace duration is at least 10 seconds:
        self.idle_grace_duration = max(10, int(self.idle_timeout * (100 - GRACE_PERCENT) // 100))
        self.idle = False
        self.idle_timer = 0
        self.idle_grace_timer = 0

    def cleanup(self) -> None:
        self.cancel_idle_grace_timeout()
        self.cancel_idle_timeout()

    def get_info(self) -> dict[str, Any]:
        return {
            "idle_time": int(monotonic() - self.last_user_event),
            "idle": self.idle,
        }

    def parse_client_caps(self, _c: typedict) -> None:
        # start the timer
        self.schedule_idle_grace_timeout()
        self.schedule_idle_timeout()

    def user_event(self) -> None:
        log("user_event()")
        self.last_user_event = monotonic()
        self.cancel_idle_grace_timeout()
        self.schedule_idle_grace_timeout()
        self.cancel_idle_timeout()
        self.schedule_idle_timeout()
        if self.idle:
            self.no_idle()
        if self.notification_callbacks.pop(NotificationID.IDLE, None):
            self.notify_close(NotificationID.IDLE)

    def cancel_idle_timeout(self) -> None:
        it = self.idle_timer
        if it:
            self.idle_timer = 0
            GLib.source_remove(it)

    def schedule_idle_timeout(self) -> None:
        log("schedule_idle_timeout() idle_timer=%s, idle_timeout=%s", self.idle_timer, self.idle_timeout)
        if self.idle_timeout > 0:
            self.idle_timer = GLib.timeout_add(self.idle_timeout * 1000, self.idle_timedout)

    def cancel_idle_grace_timeout(self) -> None:
        igt = self.idle_grace_timer
        if igt:
            self.idle_grace_timer = 0
            GLib.source_remove(igt)

    def schedule_idle_grace_timeout(self) -> None:
        log("schedule_idle_grace_timeout() grace timer=%s, idle_timeout=%s", self.idle_grace_timer, self.idle_timeout)
        if self.idle_timeout > 0 and not self.is_closed():
            grace = self.idle_timeout - self.idle_grace_duration
            self.idle_grace_timer = GLib.timeout_add(max(0, int(grace * 1000)), self.idle_grace_timedout)
            log("schedule_idle_grace_timeout() timer=%s due in %i seconds", self.idle_grace_timer, grace)

    def idle_grace_timedout(self) -> None:
        self.idle_grace_timer = 0
        log("idle_grace_timedout()")
        if not self.send_notifications:
            # not much we can do!
            return
        # notify the user, giving him a chance to cancel the timeout:
        nid = NotificationID.IDLE
        if nid in self.notification_callbacks:
            return
        actions: Sequence[str] = ()
        if self.send_notifications_actions:
            actions = ("cancel", "Cancel Timeout")
        if self.session_name != "Xpra":
            summary = f"The Xpra session {self.session_name!r}"
        else:
            summary = "Xpra session"
        summary += " is about to timeout"
        body = "Unless this session sees some activity,\n" + \
               "it will be terminated soon."
        self.may_notify(nid, summary, body,
                        actions, {}, expire_timeout=10 * 1000,
                        icon_name="timer", user_callback=self.idle_notification_action)
        self.go_idle()

    def idle_notification_action(self, nid: int, action_id) -> None:
        log("idle_notification_action(%i, %s)", nid, action_id)
        if action_id == "cancel":
            self.user_event()

    def idle_timedout(self) -> None:
        self.idle_timer = 0
        p = self.protocol
        log("idle_timedout() protocol=%s", p)
        if p:
            self.disconnect(ConnectionMessage.IDLE_TIMEOUT)
        if not self.is_closed():
            self.schedule_idle_timeout()
