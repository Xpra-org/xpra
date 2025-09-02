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
from xpra.common import ConnectionMessage, FULL_INFO
from xpra.os_util import POSIX
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("network")
pinglog = Logger("network", "ping")
bandwidthlog = Logger("bandwidth")

PING_DETAILS = envbool("XPRA_PING_DETAILS", FULL_INFO > 0)
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)
AUTO_BANDWIDTH_PCT = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert 1 < AUTO_BANDWIDTH_PCT <= 100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT
BANDWIDTH_DETECTION = envbool("XPRA_BANDWIDTH_DETECTION", True)
MIN_BANDWIDTH = envint("XPRA_MIN_BANDWIDTH", 5 * 1024 * 1024)


def get_socket_bandwidth_limit(protocol) -> int:
    if not protocol:
        return 0
    # auto-detect:
    pinfo = protocol.get_info()
    socket_speed = pinfo.get("socket", {}).get("device", {}).get("speed")
    if not socket_speed:
        return 0
    bandwidthlog("get_socket_bandwidth_limit() socket_speed=%s", socket_speed)
    # auto: use 80% of socket speed if we have it:
    return socket_speed * AUTO_BANDWIDTH_PCT // 100 or 0


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
        self.jitter = 0
        self.adapter_type = ""
        self.client_load = (0, 0, 0)
        self.client_connection_data: dict[str, Any] = {}
        self.soft_bandwidth_limit = self.bandwidth_limit = self.server_bandwidth_limit
        self.bandwidth_warnings = True
        self.bandwidth_warning_time = 0
        self.hello_sent = 0.0

    def init_from(self, _protocol, server) -> None:
        self.server_bandwidth_limit = server.bandwidth_limit
        self.bandwidth_detection = server.bandwidth_detection

    def cleanup(self) -> None:
        self.cancel_ping_echo_timers()

    def get_caps(self) -> dict[str, Any]:
        # legacy flag
        return {"ping-echo-sourceid": True}

    def parse_client_caps(self, c: typedict) -> None:
        self.client_connection_data = c.dictget("connection-data", {})
        ccd = typedict(self.client_connection_data)
        self.adapter_type = ccd.strget("adapter-type")
        self.jitter = ccd.intget("jitter", 0)
        bandwidth_limit = c.intget("bandwidth-limit", 0)
        if getattr(self, "mmap_size", 0) > 0:
            log("mmap enabled, ignoring bandwidth-limit")
            self.bandwidth_limit = 0
            self.bandwidth_detection = False
            self.jitter = 0
        else:
            limit = self.server_bandwidth_limit or get_socket_bandwidth_limit(self.protocol)
            self.bandwidth_limit = min(limit, bandwidth_limit)
            if self.bandwidth_detection:
                self.bandwidth_detection = c.boolget("bandwidth-detection", False)
        bandwidthlog("server bandwidth-limit=%s, client bandwidth-limit=%s, value=%s, detection=%s",
                     self.server_bandwidth_limit, bandwidth_limit, self.bandwidth_limit, self.bandwidth_detection)

    def get_info(self) -> dict[str, Any]:
        lpe = 0
        if self.last_ping_echoed_time > 0:
            lpe = int(monotonic() * 1000 - self.last_ping_echoed_time)
        info = {
            "bandwidth-limit": {
                "setting": self.bandwidth_limit or 0,
                "detection": self.bandwidth_detection,
                "actual": self.soft_bandwidth_limit or 0,
            },
            "jitter": self.jitter,
            "last-ping-echo": lpe,
            "adapter-type": self.adapter_type,
        }
        return info

    ######################################################################
    # pings:
    def ping(self) -> None:
        if not self.hello_sent:
            return
        now = monotonic()
        elapsed = now - self.hello_sent
        if elapsed < 5:
            return
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

    def update_bandwidth_limits(self) -> None:
        if not self.bandwidth_detection:
            return
        mmap_size = getattr(self, "mmap_size", 0)
        if mmap_size > 0:
            return
        # calculate soft bandwidth limit based on send congestion data:
        bandwidth_limit = 0
        if BANDWIDTH_DETECTION:
            bandwidth_limit = self.statistics.avg_congestion_send_speed
            bandwidthlog("avg_congestion_send_speed=%s", bandwidth_limit)
            if bandwidth_limit > 20 * 1024 * 1024:
                # ignore congestion speed if greater 20Mbps
                bandwidth_limit = 0
        if (self.bandwidth_limit or 0) > 0:
            # command line options could overrule what we detect?
            bandwidth_limit = min(self.bandwidth_limit, bandwidth_limit)
        if bandwidth_limit > 0:
            bandwidth_limit = max(MIN_BANDWIDTH, bandwidth_limit)
        self.soft_bandwidth_limit = bandwidth_limit
        bandwidthlog("update_bandwidth_limits() bandwidth_limit=%s, soft bandwidth limit=%s",
                     self.bandwidth_limit, bandwidth_limit)
        # figure out how to distribute the bandwidth amongst the windows,
        # we use the window size,
        # (we should use the number of bytes actually sent: framerate, compression, etc..)
        window_weight = {}
        for wid, ws in self.window_sources.items():
            weight = 0
            if not ws.suspended:
                ww, wh = ws.window_dimensions
                # try to reserve bandwidth for at least one screen update,
                # and add the number of pixels damaged:
                weight = ww * wh + ws.statistics.get_damage_pixels()
            window_weight[wid] = weight
        bandwidthlog("update_bandwidth_limits() window weights=%s", window_weight)
        total_weight = max(1, sum(window_weight.values()))
        for wid, ws in self.window_sources.items():
            if bandwidth_limit == 0:
                ws.bandwidth_limit = 0
            else:
                weight = window_weight.get(wid, 0)
                ws.bandwidth_limit = max(MIN_BANDWIDTH // 10, bandwidth_limit * weight // total_weight)
