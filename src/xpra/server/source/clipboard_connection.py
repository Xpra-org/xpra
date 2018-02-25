# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections import deque

from xpra.log import Logger
log = Logger("clipboard")

from xpra.net.compression import Compressible
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.util import envint
from xpra.os_util import monotonic_time

MAX_CLIPBOARD_LIMIT = envint("XPRA_CLIPBOARD_LIMIT", 30)
MAX_CLIPBOARD_LIMIT_DURATION = envint("XPRA_CLIPBOARD_LIMIT_DURATION", 3)


class ClipboardConnection(StubSourceMixin):

    def init_state(self):
        self.clipboard_enabled = False
        self.clipboard_notifications = False
        self.clipboard_notifications_current = 0
        self.clipboard_notifications_pending = 0
        self.clipboard_set_enabled = False
        self.clipboard_progress_timer = None
        self.clipboard_stats = deque(maxlen=MAX_CLIPBOARD_LIMIT*MAX_CLIPBOARD_LIMIT_DURATION)

    def cleanup(self):
        self.cancel_clipboard_progress_timer()

    def parse_client_caps(self, c):
        self.clipboard_enabled = c.boolget("clipboard", True)
        self.clipboard_notifications = c.boolget("clipboard.notifications")
        self.clipboard_set_enabled = c.boolget("clipboard.set_enabled")
        log("client clipboard: enabled=%s, notifications=%s, set-enabled=%s", self.clipboard_enabled, self.clipboard_notifications, self.clipboard_set_enabled)

    def get_info(self):
        return {
            "clipboard"                 : self.clipboard_enabled,
            "clipboard_notifications"   : True,
            }


    def send_clipboard_enabled(self, reason=""):
        if not self.hello_sent:
            return
        self.send_async("set-clipboard-enabled", self.clipboard_enabled, reason)

    def cancel_clipboard_progress_timer(self):
        cpt = self.clipboard_progress_timer
        if cpt:
            self.clipboard_progress_timer = None
            self.source_remove(cpt)

    def send_clipboard_progress(self, count):
        if not self.clipboard_notifications or not self.hello_sent or self.clipboard_progress_timer:
            return
        #always set "pending" to the latest value:
        self.clipboard_notifications_pending = count
        #but send the latest value via a timer to tame toggle storms:
        def may_send_progress_update():
            self.clipboard_progress_timer = None
            if self.clipboard_notifications_current!=self.clipboard_notifications_pending:
                self.clipboard_notifications_current = self.clipboard_notifications_pending
                log("sending clipboard-pending-requests=%s to %s", self.clipboard_notifications_current, self)
                self.send_more("clipboard-pending-requests", self.clipboard_notifications_current)
        delay = (count==0)*100
        self.clipboard_progress_timer = self.timeout_add(delay, may_send_progress_update)

    def send_clipboard(self, packet):
        if not self.clipboard_enabled or self.suspended or not self.hello_sent:
            return
        now = monotonic_time()
        self.clipboard_stats.append(now)
        if len(self.clipboard_stats)>=MAX_CLIPBOARD_LIMIT:
            event = self.clipboard_stats[-MAX_CLIPBOARD_LIMIT]
            elapsed = now-event
            log("send_clipboard(..) elapsed=%.2f, clipboard_stats=%s", elapsed, self.clipboard_stats)
            if elapsed<1:
                msg = "more than %s clipboard requests per second!" % MAX_CLIPBOARD_LIMIT
                log.warn("Warning: %s", msg)
                #disable if this rate is sustained for more than S seconds:
                events = [x for x in self.clipboard_stats if x>(now-MAX_CLIPBOARD_LIMIT_DURATION)]
                if len(events)>=MAX_CLIPBOARD_LIMIT*MAX_CLIPBOARD_LIMIT_DURATION:
                    log.warn(" limit sustained for more than %i seconds,", MAX_CLIPBOARD_LIMIT_DURATION)
                    log.warn(" the clipboard is now disabled")
                    self.clipboard_enabled = False
                    self.send_clipboard_enabled(msg)
                return
        #call compress_clibboard via the work queue:
        self.encode_work_queue.put((True, self.compress_clipboard, packet))

    def compress_clipboard(self, packet):
        #Note: this runs in the 'encode' thread!
        packet = list(packet)
        for i in range(len(packet)):
            v = packet[i]
            if type(v)==Compressible:
                packet[i] = self.compressed_wrapper(v.datatype, v.data)
        self.queue_packet(packet)
