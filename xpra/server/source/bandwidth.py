# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("network", "bandwidth")

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
    log("get_socket_bandwidth_limit() socket_speed=%s", socket_speed)
    # auto: use 80% of socket speed if we have it:
    return socket_speed * AUTO_BANDWIDTH_PCT // 100 or 0


class BandwidthConnection(StubClientConnection):

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return caps.boolget("network-state")

    def init_state(self) -> None:
        self.jitter = 0
        self.adapter_type = ""
        self.client_connection_data: dict[str, Any] = {}
        self.soft_bandwidth_limit = self.bandwidth_limit = self.server_bandwidth_limit
        self.bandwidth_warnings = True
        self.bandwidth_warning_time = 0

    def init_from(self, _protocol, server) -> None:
        self.server_bandwidth_limit = server.bandwidth_limit
        self.bandwidth_detection = server.bandwidth_detection

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
        log("server bandwidth-limit=%s, client bandwidth-limit=%s, value=%s, detection=%s",
            self.server_bandwidth_limit, bandwidth_limit, self.bandwidth_limit, self.bandwidth_detection)

    def get_info(self) -> dict[str, Any]:
        info = {
            "bandwidth": {
                "limit": self.bandwidth_limit or 0,
                "detection": self.bandwidth_detection,
                "actual": self.soft_bandwidth_limit or 0,
            },
            "jitter": self.jitter,
            "adapter-type": self.adapter_type,
        }
        return info

    def update_connection_data(self, data: dict) -> None:
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
            log("avg_congestion_send_speed=%s", bandwidth_limit)
            if bandwidth_limit > 20 * 1024 * 1024:
                # ignore congestion speed if greater 20Mbps
                bandwidth_limit = 0
        if (self.bandwidth_limit or 0) > 0:
            # command line options could overrule what we detect?
            bandwidth_limit = min(self.bandwidth_limit, bandwidth_limit)
        if bandwidth_limit > 0:
            bandwidth_limit = max(MIN_BANDWIDTH, bandwidth_limit)
        self.soft_bandwidth_limit = bandwidth_limit
        log("update_bandwidth_limits() bandwidth_limit=%s, soft bandwidth limit=%s",
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
        log("update_bandwidth_limits() window weights=%s", window_weight)
        total_weight = max(1, sum(window_weight.values()))
        for wid, ws in self.window_sources.items():
            if bandwidth_limit == 0:
                ws.bandwidth_limit = 0
            else:
                weight = window_weight.get(wid, 0)
                ws.bandwidth_limit = max(MIN_BANDWIDTH // 10, bandwidth_limit * weight // total_weight)
