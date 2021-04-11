# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import envint, IDLE_TIMEOUT, XPRA_IDLE_NOTIFICATION_ID
from xpra.os_util import monotonic_time
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("timeout")

GRACE_PERCENT = envint("XPRA_GRACE_PERCENT", 90)


class IdleMixin(StubSourceMixin):

    def __init__(self):
        self.idle_timeout = 0

    def init_from(self, _protocol, server):
        self.idle_timeout = server.idle_timeout

    def init_state(self):
        self.last_user_event = monotonic_time()
        #grace duration is at least 10 seconds:
        self.idle_grace_duration = max(10, int(self.idle_timeout*(100-GRACE_PERCENT)//100))
        self.idle = False
        self.idle_timer = None
        self.idle_grace_timer = None

    def cleanup(self):
        self.cancel_idle_grace_timeout()
        self.cancel_idle_timeout()

    def get_info(self):
        return {
                "idle_time"         : int(monotonic_time()-self.last_user_event),
                "idle"              : self.idle,
                }


    def parse_client_caps(self, _c):
        #start the timer
        self.schedule_idle_grace_timeout()
        self.schedule_idle_timeout()

    def user_event(self):
        log("user_event()")
        self.last_user_event = monotonic_time()
        self.cancel_idle_grace_timeout()
        self.schedule_idle_grace_timeout()
        self.cancel_idle_timeout()
        self.schedule_idle_timeout()
        if self.idle:
            self.no_idle()
        try:
            self.notification_callbacks.pop(XPRA_IDLE_NOTIFICATION_ID)
        except KeyError:
            pass
        else:
            self.notify_close(XPRA_IDLE_NOTIFICATION_ID)


    def cancel_idle_timeout(self):
        it = self.idle_timer
        if it:
            self.idle_timer = None
            self.source_remove(it)

    def schedule_idle_timeout(self):
        log("schedule_idle_timeout() idle_timer=%s, idle_timeout=%s", self.idle_timer, self.idle_timeout)
        if self.idle_timeout>0:
            self.idle_timer = self.timeout_add(self.idle_timeout*1000, self.idle_timedout)

    def cancel_idle_grace_timeout(self):
        igt = self.idle_grace_timer
        if igt:
            self.idle_grace_timer = None
            self.source_remove(igt)

    def schedule_idle_grace_timeout(self):
        log("schedule_idle_grace_timeout() grace timer=%s, idle_timeout=%s", self.idle_grace_timer, self.idle_timeout)
        if self.idle_timeout>0 and not self.is_closed():
            grace = self.idle_timeout - self.idle_grace_duration
            self.idle_grace_timer = self.timeout_add(max(0, int(grace*1000)), self.idle_grace_timedout)
            log("schedule_idle_grace_timeout() timer=%s due in %i seconds", self.idle_grace_timer, grace)

    def idle_grace_timedout(self):
        self.idle_grace_timer = None
        log("idle_grace_timedout()")
        if not self.send_notifications:
            #not much we can do!
            return
        #notify the user, giving him a chance to cancel the timeout:
        nid = XPRA_IDLE_NOTIFICATION_ID
        if nid in self.notification_callbacks:
            return
        actions = ()
        if self.send_notifications_actions:
            actions = ("cancel", "Cancel Timeout")
        if self.session_name!="Xpra":
            summary = "The Xpra session %s" % self.session_name
        else:
            summary = "Xpra session"
        summary += " is about to timeout"
        body = "Unless this session sees some activity,\n" + \
               "it will be terminated soon."
        self.may_notify(nid, summary, body,
                        actions, {}, expire_timeout=10*1000,
                        icon_name="timer", user_callback=self.idle_notification_action)
        self.go_idle()

    def idle_notification_action(self, nid, action_id):
        log("idle_notification_action(%i, %s)", nid, action_id)
        if action_id=="cancel":
            self.user_event()

    def idle_timedout(self):
        self.idle_timer = None
        p = self.protocol
        log("idle_timedout() protocol=%s", p)
        if p:
            self.disconnect(IDLE_TIMEOUT)
        if not self.is_closed():
            self.schedule_idle_timeout()
