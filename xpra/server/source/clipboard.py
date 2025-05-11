# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Any, Deque
from collections import deque
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.server.source.stub import StubClientConnection
from xpra.platform.features import CLIPBOARDS
from xpra.common import BACKWARDS_COMPATIBLE
from xpra.net.common import Packet
from xpra.util.objects import typedict
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("clipboard")

GLib = gi_import("GLib")

MAX_CLIPBOARD_LIMIT = envint("XPRA_CLIPBOARD_LIMIT", 30)
MAX_CLIPBOARD_LIMIT_DURATION = envint("XPRA_CLIPBOARD_LIMIT_DURATION", 3)


class ClipboardConnection(StubClientConnection):

    PREFIX = "clipboard"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return caps.boolget("clipboard")

    def init_state(self) -> None:
        self.clipboard_enabled = False
        self.clipboard_notifications = False
        self.clipboard_notifications_current = 0
        self.clipboard_notifications_pending = 0
        self.clipboard_progress_timer: int = 0
        self.clipboard_stats: Deque[float] = deque(maxlen=MAX_CLIPBOARD_LIMIT * MAX_CLIPBOARD_LIMIT_DURATION)
        self.clipboard_greedy = False
        self.clipboard_want_targets = False
        self.clipboard_selections = CLIPBOARDS
        self.clipboard_preferred_targets: Sequence[str] = ()

    def cleanup(self) -> None:
        self.cancel_clipboard_progress_timer()

    def parse_client_caps(self, c: typedict) -> None:
        ccaps = c.get(ClipboardConnection.PREFIX)
        if ccaps and isinstance(ccaps, dict):
            ccaps = typedict(ccaps)
            self.clipboard_enabled = ccaps.boolget("enabled", True)
            self.clipboard_notifications = ccaps.boolget("notifications")
            self.clipboard_greedy = ccaps.boolget("greedy")
            self.clipboard_want_targets = ccaps.boolget("want_targets")
            self.clipboard_selections = ccaps.strtupleget("selections", CLIPBOARDS)
            self.clipboard_preferred_targets = ccaps.strtupleget("preferred-targets", ())
        log("client clipboard: enabled=%s, notifications=%s",
            self.clipboard_enabled, self.clipboard_notifications)
        log("client clipboard: greedy=%s, want_targets=%s, selections=%s",
            self.clipboard_greedy, self.clipboard_want_targets, self.clipboard_selections)

    def get_info(self) -> dict[str, Any]:
        return {
            ClipboardConnection.PREFIX: {
                "enabled": self.clipboard_enabled,
                "notifications": self.clipboard_notifications,
                "greedy": self.clipboard_greedy,
                "want-targets": self.clipboard_want_targets,
                "preferred-targets": self.clipboard_preferred_targets,
                "selections": self.clipboard_selections,
            },
        }

    def send_clipboard_enabled(self, reason: str = "") -> None:
        if not self.hello_sent:
            return
        packet_type = "set-clipboard-enabled" if BACKWARDS_COMPATIBLE else "clipboard-status"
        self.send_async(packet_type, self.clipboard_enabled, reason)

    def cancel_clipboard_progress_timer(self) -> None:
        cpt = self.clipboard_progress_timer
        if cpt:
            self.clipboard_progress_timer = 0
            GLib.source_remove(cpt)

    def send_clipboard_progress(self, count: int) -> None:
        if not self.clipboard_notifications or not self.hello_sent or self.clipboard_progress_timer:
            return
        # always set "pending" to the latest value:
        self.clipboard_notifications_pending = count

        # but send the latest value via a timer to tame toggle storms:

        def may_send_progress_update() -> None:
            self.clipboard_progress_timer = 0
            if self.clipboard_notifications_current != self.clipboard_notifications_pending:
                self.clipboard_notifications_current = self.clipboard_notifications_pending
                log("sending clipboard-pending-requests=%s to %s", self.clipboard_notifications_current, self)
                self.send_more("clipboard-pending-requests", self.clipboard_notifications_current)

        delay = (count == 0) * 100
        self.clipboard_progress_timer = GLib.timeout_add(delay, may_send_progress_update)

    def send_clipboard(self, packet) -> None:
        if not self.clipboard_enabled or not self.hello_sent:
            return
        if getattr(self, "suspended", False):
            return
        now = monotonic()
        self.clipboard_stats.append(now)
        if len(self.clipboard_stats) >= MAX_CLIPBOARD_LIMIT:
            event = self.clipboard_stats[-MAX_CLIPBOARD_LIMIT]
            elapsed = now - event
            log("send_clipboard(..) elapsed=%.2f, clipboard_stats=%s", elapsed, self.clipboard_stats)
            if elapsed < 1:
                msg = f"more than {MAX_CLIPBOARD_LIMIT} clipboard requests per second!"
                log.warn("Warning: %s", msg)
                # disable if this rate is sustained for more than S seconds:
                events = [x for x in tuple(self.clipboard_stats) if x > (now - MAX_CLIPBOARD_LIMIT_DURATION)]
                log("%i events in the last %i seconds: %s", len(events), MAX_CLIPBOARD_LIMIT_DURATION, events)
                if len(events) >= MAX_CLIPBOARD_LIMIT * MAX_CLIPBOARD_LIMIT_DURATION:
                    log.warn(" limit sustained for more than %i seconds,", MAX_CLIPBOARD_LIMIT_DURATION)
                return
        # call compress_clibboard via the encode work queue:
        self.queue_encode((True, self.compress_clipboard, (packet,)))

    def compress_clipboard(self, packet: Packet) -> None:
        # pylint: disable=import-outside-toplevel
        from xpra.net.compression import Compressible, compressed_wrapper
        # Note: this runs in the 'encode' thread!
        packet = list(packet)
        for i, item in enumerate(packet):
            if isinstance(item, Compressible):
                packet[i] = compressed_wrapper(item.datatype, item.data, level=9, can_inline=False, brotli=True)
        self.queue_packet(tuple(packet))
