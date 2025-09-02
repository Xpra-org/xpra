# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
from time import monotonic
from typing import Any

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.common import ConnectionMessage, FULL_INFO, BACKWARDS_COMPATIBLE
from xpra.os_util import POSIX
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("network", "ping")

PING_DETAILS = envbool("XPRA_PING_DETAILS", FULL_INFO > 0)
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)


class PingConnection(StubClientConnection):

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        if caps.boolget("ping"):
            return True
        if typedict(caps.dictget("network") or {}).intget("pings") > 0:
            return True
        if BACKWARDS_COMPATIBLE:
            return caps.boolget("ping-echo-sourceid")  # legacy clients
        return False

    def init_state(self) -> None:
        self.last_ping_echoed_time = 0
        self.check_ping_echo_timers: dict[int, int] = {}
        self.client_load = (0, 0, 0)
        self.hello_sent = 0.0

    def cleanup(self) -> None:
        self.cancel_ping_echo_timers()

    def get_caps(self) -> dict[str, Any]:
        if BACKWARDS_COMPATIBLE:
            return {"ping-echo-sourceid": True}  # legacy flag
        return {}

    def get_info(self) -> dict[str, Any]:
        lpe = self.last_ping_echoed_time
        if lpe > 0:
            return {
                "last-ping-echo": int(monotonic() * 1000 - lpe),
            }
        return {}

    def ping(self) -> None:
        if not self.hello_sent:
            return
        now = monotonic()
        elapsed = now - self.hello_sent
        if elapsed < 5:
            return
        # NOTE: all ping time/echo time/load avg values are in milliseconds
        now_ms = int(1000 * monotonic())
        log("sending ping to %s with time=%s", self.protocol, now_ms)
        self.send_async("ping", now_ms, int(time.time() * 1000), will_have_more=False)
        timeout = PING_TIMEOUT
        self.check_ping_echo_timers[now_ms] = GLib.timeout_add(timeout * 1000,
                                                               self.check_ping_echo_timeout, now_ms, timeout)

    def check_ping_echo_timeout(self, now_ms: int, timeout: int) -> None:
        self.check_ping_echo_timers.pop(now_ms, None)
        if self.is_closed():
            return
        expired = self.last_ping_echoed_time < now_ms
        message = f"waited {timeout} seconds without a response" if expired else ""
        log(f"check_ping_echo_timeout {message}")
        if expired:
            self.disconnect(ConnectionMessage.CLIENT_PING_TIMEOUT, message)

    def cancel_ping_echo_timers(self) -> None:
        timers = self.check_ping_echo_timers.values()
        self.check_ping_echo_timers = {}
        for t in timers:
            GLib.source_remove(t)

    def process_ping(self, time_to_echo, sid) -> None:
        l1, l2, l3 = 0, 0, 0
        cl = -1
        if PING_DETAILS:
            # send back the load average:
            if POSIX:
                fl1, fl2, fl3 = os.getloadavg()
                l1, l2, l3 = int(fl1 * 1000), int(fl2 * 1000), int(fl3 * 1000)
            # and the last client ping latency we measured (if any):
            stats = getattr(self, "statistics", None)
            if stats and stats.client_ping_latency:
                _, cl = stats.client_ping_latency[-1]
                cl = int(1000.0 * cl)
        self.send_async("ping_echo", time_to_echo, l1, l2, l3, cl, sid, will_have_more=False)
        log(f"ping: sending echo for time={time_to_echo} and {sid=}")

    def process_ping_echo(self, packet) -> None:
        echoedtime = packet.get_u64(1)
        l1 = packet.get_u64(2)
        l2 = packet.get_u64(3)
        l3 = packet.get_u64(4)
        server_ping_latency = packet.get_i64(5)
        timer = self.check_ping_echo_timers.pop(echoedtime, None)
        if timer:
            GLib.source_remove(timer)
        self.last_ping_echoed_time = echoedtime
        client_ping_latency = monotonic() - echoedtime / 1000.0
        # optional dependency:
        stats = getattr(self, "statistics", None)
        if stats and 0 < client_ping_latency < 60:
            stats.client_ping_latency.append((monotonic(), client_ping_latency))
        self.client_load = l1, l2, l3
        if 0 <= server_ping_latency < 60000 and stats:
            stats.server_ping_latency.append((monotonic(), server_ping_latency / 1000.0))
        log(f"ping echo client load={self.client_load}, "
            f"latency measured from server={client_ping_latency}ms, from client={server_ping_latency}ms")
