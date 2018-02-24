# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("timeout")

from xpra.util import envint, XPRA_IDLE_NOTIFICATION_ID
from xpra.os_util import monotonic_time
from xpra.server.source.stub_source_mixin import StubSourceMixin

GRACE_PERCENT = envint("XPRA_GRACE_PERCENT", 90)


class IdleMixin(StubSourceMixin):

    def __init__(self, idle_timeout, idle_timeout_cb, idle_grace_timeout_cb):
        self.idle_timeout = idle_timeout
        self.idle_timeout_cb = idle_timeout_cb
        self.idle_grace_timeout_cb = idle_grace_timeout_cb
        self.last_user_event = monotonic_time()
        #grace duration is at least 10 seconds:
        self.idle_grace_duration = max(10, int(self.idle_timeout*(100-GRACE_PERCENT)//100))
        self.idle = False
        self.idle_timer = None
        self.idle_grace_timer = None
        self.schedule_idle_grace_timeout()
        self.schedule_idle_timeout()

    def cleanup(self):
        self.cancel_idle_grace_timeout()
        self.cancel_idle_timeout()

    def get_info(self):
        return {
                "idle_time"         : int(monotonic_time()-self.last_user_event),
                "idle"              : self.idle,
                }


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

    def idle_grace_timedout(self):
        self.idle_grace_timer = None
        log("idle_grace_timedout() callback=%s", self.idle_grace_timeout_cb)
        self.idle_grace_timeout_cb(self)

    def idle_timedout(self):
        self.idle_timer = None
        log("idle_timedout() callback=%s", self.idle_timeout_cb)
        self.idle_timeout_cb(self)
        if not self.is_closed():
            self.schedule_idle_timeout()
