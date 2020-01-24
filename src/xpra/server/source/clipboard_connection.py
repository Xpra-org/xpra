# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections import deque

from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.platform.features import CLIPBOARDS
from xpra.util import envint, typedict
from xpra.os_util import monotonic_time
from xpra.log import Logger

log = Logger("clipboard")

MAX_CLIPBOARD_LIMIT = envint("XPRA_CLIPBOARD_LIMIT", 30)
MAX_CLIPBOARD_LIMIT_DURATION = envint("XPRA_CLIPBOARD_LIMIT_DURATION", 3)


class ClipboardConnection(StubSourceMixin):

    @classmethod
    def is_needed(cls, caps : typedict) -> bool:
        return caps.boolget("clipboard")


    def init_state(self):
        self.clipboard_enabled = False
        self.clipboard_notifications = False
        self.clipboard_notifications_current = 0
        self.clipboard_notifications_pending = 0
        self.clipboard_progress_timer = None
        self.clipboard_stats = deque(maxlen=MAX_CLIPBOARD_LIMIT*MAX_CLIPBOARD_LIMIT_DURATION)
        self.clipboard_greedy = False
        self.clipboard_want_targets = False
        self.clipboard_client_selections = CLIPBOARDS
        self.clipboard_preferred_targets = ()

    def cleanup(self):
        self.cancel_clipboard_progress_timer()

    def parse_client_caps(self, c : typedict):
        self.clipboard_enabled = c.boolget("clipboard", False)
        self.clipboard_notifications = c.boolget("clipboard.notifications")
        log("client clipboard: enabled=%s, notifications=%s",
            self.clipboard_enabled, self.clipboard_notifications)
        self.clipboard_greedy = c.boolget("clipboard.greedy")
        self.clipboard_want_targets = c.boolget("clipboard.want_targets")
        self.clipboard_client_selections = c.strtupleget("clipboard.selections", CLIPBOARDS)
        self.clipboard_contents_slice_fix = c.boolget("clipboard.contents-slice-fix")
        self.clipboard_preferred_targets = c.strtupleget("clipboard.preferred-targets", ())
        log("client clipboard: greedy=%s, want_targets=%s, client_selections=%s, contents_slice_fix=%s",
            self.clipboard_greedy, self.clipboard_want_targets,
            self.clipboard_client_selections, self.clipboard_contents_slice_fix)
        if self.clipboard_enabled and not self.clipboard_contents_slice_fix:
            log.info("client clipboard does not include contents slice fix")

    def get_info(self) -> dict:
        return {
            "clipboard" : {
                "enabled"               : self.clipboard_enabled,
                "notifications"         : self.clipboard_notifications,
                "greedy"                : self.clipboard_greedy,
                "want-targets"          : self.clipboard_want_targets,
                "preferred-targets"     : self.clipboard_preferred_targets,
                "selections"            : self.clipboard_client_selections,
                "contents-slice-fix"    : self.clipboard_contents_slice_fix,
                },
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

    def send_clipboard_progress(self, count : int):
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
        if not self.clipboard_enabled or not self.hello_sent:
            return
        if getattr(self, "suspended", False):
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
                log("%i events in the last %i seconds: %s", len(events), MAX_CLIPBOARD_LIMIT_DURATION, events)
                if len(events)>=MAX_CLIPBOARD_LIMIT*MAX_CLIPBOARD_LIMIT_DURATION:
                    log.warn(" limit sustained for more than %i seconds,", MAX_CLIPBOARD_LIMIT_DURATION)
                return
        #call compress_clibboard via the encode work queue:
        self.queue_encode((True, self.compress_clipboard, packet))

    def compress_clipboard(self, packet):
        from xpra.net.compression import Compressible, compressed_wrapper
        #Note: this runs in the 'encode' thread!
        packet = list(packet)
        for i, item in enumerate(packet):
            if isinstance(item, Compressible):
                if self.brotli:
                    packet[i] = compressed_wrapper(item.datatype, item.data,
                                                               level=9, brotli=True, can_inline=False)
                else:
                    packet[i] = self.compressed_wrapper(item.datatype, item.data)
        self.queue_packet(packet)
