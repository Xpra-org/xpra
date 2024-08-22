# This file is part of Xpra.
# Copyright (C) 2010-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
from time import monotonic
from typing import Any

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.common import ConnectionMessage, FULL_INFO
from xpra.os_util import POSIX
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("network")
pinglog = Logger("network", "ping")

PING_DETAILS = envbool("XPRA_PING_DETAILS", FULL_INFO > 0)
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)


class NetworkStateMixin(StubSourceMixin):

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return any((
            caps.boolget("network-state"),
            typedict(caps.dictget("network") or {}).intget("pings") > 0,
            caps.boolget("ping-echo-sourceid"),  # legacy clients
        ))

    def init_state(self) -> None:
        self.last_ping_echoed_time = 0
        self.check_ping_echo_timers: dict[int, int] = {}
        self.ping_timer = 0
        self.bandwidth_limit = 0
        self.client_load = (0, 0, 0)
        self.client_connection_data: dict[str, Any] = {}

    def cleanup(self) -> None:
        self.cancel_ping_echo_timers()
        self.cancel_ping_timer()

    def get_caps(self) -> dict[str, Any]:
        # legacy flag
        return {"ping-echo-sourceid": True}

    def get_info(self) -> dict[str, Any]:
        lpe = 0
        if self.last_ping_echoed_time > 0:
            lpe = int(monotonic() * 1000 - self.last_ping_echoed_time)
        info = {
            "bandwidth-limit": {
                "setting": self.bandwidth_limit or 0,
            },
            "last-ping-echo": lpe,
        }
        return info

    ######################################################################
    # pings:
    def ping(self) -> None:
        self.ping_timer = 0
        # NOTE: all ping time/echo time/load avg values are in milliseconds
        now_ms = int(1000 * monotonic())
        pinglog("sending ping to %s with time=%s", self.protocol, now_ms)
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
        pinglog(f"check_ping_echo_timeout {message}")
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
        pinglog(f"ping: sending echo for time={time_to_echo} and {sid=}")
        # if the client is pinging us, ping it too:
        if not self.ping_timer:
            self.ping_timer = GLib.timeout_add(500, self.ping)
            pinglog(f"starting client ping timer: {self.ping_timer}")

    def cancel_ping_timer(self) -> None:
        pt = self.ping_timer
        if pt:
            self.ping_timer = 0
            GLib.source_remove(pt)

    def process_ping_echo(self, packet) -> None:
        echoedtime, l1, l2, l3, server_ping_latency = packet[1:6]
        timer = self.check_ping_echo_timers.pop(echoedtime, None)
        if timer:
            GLib.source_remove(timer)
        self.last_ping_echoed_time = echoedtime
        client_ping_latency = monotonic() - echoedtime / 1000.0
        stats = getattr(self, "statistics", None)
        if stats and 0 < client_ping_latency < 60:
            stats.client_ping_latency.append((monotonic(), client_ping_latency))
        self.client_load = l1, l2, l3
        if 0 <= server_ping_latency < 60000 and stats:
            stats.server_ping_latency.append((monotonic(), server_ping_latency / 1000.0))
        pinglog(f"ping echo client load={self.client_load}, "
                f"latency measured from server={client_ping_latency}ms, from client={server_ping_latency}ms")

    def update_connection_data(self, data) -> None:
        log("update_connection_data(%s)", data)
        if not isinstance(data, dict):
            raise TypeError("connection-data must be a dictionary")
        self.client_connection_data = data
