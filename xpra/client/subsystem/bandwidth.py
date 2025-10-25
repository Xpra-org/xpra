# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any
from collections.abc import Callable

from xpra.net.device_info import (
    get_NM_adapter_type, get_device_value, guess_adapter_type,
    jitter_for_adapter_type, guess_bandwidth_limit,
)
from xpra.util.objects import typedict
from xpra.util.env import envint
from xpra.client.base.stub import StubClientMixin
from xpra.util.parsing import parse_with_unit
from xpra.log import Logger

log = Logger("network", "bandwidth")


AUTO_BANDWIDTH_PCT: int = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert 1 < AUTO_BANDWIDTH_PCT <= 100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT


def parse_speed(v) -> int:
    return parse_with_unit("speed", v) or 0


class BandwidthClient(StubClientMixin):
    """
    Expose bandwidth information
    """

    def __init__(self):
        self.bandwidth_limit: int = 0
        self.bandwidth_detection: bool = False
        self.server_bandwidth_limit: int = 0

    def init(self, opts) -> None:
        self.bandwidth_limit = parse_with_unit("bandwidth-limit", opts.bandwidth_limit) or 0
        self.bandwidth_detection = opts.bandwidth_detection
        log("init bandwidth_limit=%s", self.bandwidth_limit)

    def get_info(self) -> dict[str, Any]:
        return {
            "network": {
                "bandwidth-limit": self.bandwidth_limit,
                "bandwidth-detection": self.bandwidth_detection,
            }
        }

    def get_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "network-state": True,
        }
        # get socket speed if we have it:
        pinfo = self._protocol.get_info()
        device_info = pinfo.get("socket", {}).get("device", {})
        try:
            coptions = self._protocol._conn.options
        except AttributeError:
            coptions = {}
        log("get_caps() device_info=%s, connection options=%s", device_info, coptions)

        def device_value(attr: str, conv: Callable = str, default_value: Any = ""):
            return get_device_value(coptions, device_info, attr, conv, default_value)

        device_name = device_info.get("name", "")
        log("get_caps() found device name=%s", device_name)
        default_adapter_type = guess_adapter_type(get_NM_adapter_type(device_name) or device_name)
        adapter_type = device_value("adapter-type", str, default_adapter_type)
        log("get_caps() found adapter-type=%s", adapter_type)
        socket_speed = device_value("speed", parse_speed, 0)
        log("get_caps() found socket_speed=%s", socket_speed)
        jitter = device_value("jitter", int, jitter_for_adapter_type(adapter_type))
        log("get_caps() found jitter=%s", jitter)

        connection_data = {}
        if adapter_type:
            connection_data["adapter-type"] = adapter_type
        if jitter >= 0:
            connection_data["jitter"] = jitter
        if socket_speed:
            connection_data["speed"] = socket_speed
        log("get_caps() connection-data=%s", connection_data)
        caps["connection-data"] = connection_data

        bandwidth_limit = self.bandwidth_limit
        log("bandwidth-limit setting=%s, socket-speed=%s", self.bandwidth_limit, socket_speed)
        if bandwidth_limit is None:
            if socket_speed:
                # auto: use 80% of socket speed if we have it:
                bandwidth_limit = socket_speed * AUTO_BANDWIDTH_PCT // 100 or 0
            else:
                bandwidth_limit = guess_bandwidth_limit(adapter_type)
        log("bandwidth-limit capability=%s", bandwidth_limit)
        if bandwidth_limit > 0:
            caps["bandwidth-limit"] = bandwidth_limit
        caps["bandwidth-detection"] = self.bandwidth_detection
        return caps

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_bandwidth_limit = c.intget("network.bandwidth-limit")
        log(f"{self.server_bandwidth_limit=}")
        return True

    def send_bandwidth_limit(self) -> None:
        log("send_bandwidth_limit() bandwidth-limit=%i", self.bandwidth_limit)
        self.send("bandwidth-limit", self.bandwidth_limit)
