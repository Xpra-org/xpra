# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.server.subsystem.stub import StubServerMixin
from xpra.util.parsing import parse_with_unit
from xpra.util.stats import std_unit
from xpra.net.common import Packet
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("network", "bandwidth")

MIN_BANDWIDTH_LIMIT = envint("XPRA_MIN_BANDWIDTH_LIMIT", 1024 * 1024)
MAX_BANDWIDTH_LIMIT = envint("XPRA_MAX_BANDWIDTH_LIMIT", 10 * 1024 * 1024 * 1024)


class BandwidthServer(StubServerMixin):
    """
    Adds bandwidth management
    """
    PREFIX = "bandwidth"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.bandwidth_limit = 0
        self.bandwidth_detection = False

    def init(self, opts) -> None:
        self.bandwidth_limit = parse_with_unit("bandwidth-limit", opts.bandwidth_limit) or 0
        self.bandwidth_detection = opts.bandwidth_detection
        log("bandwidth-limit(%s)=%s", opts.bandwidth_limit, self.bandwidth_limit)

    def get_info(self, _source=None) -> dict[str, Any]:
        info = {
            "limit": self.bandwidth_limit or 0,
            "detection": self.bandwidth_detection,
        }
        return {BandwidthServer.PREFIX: info}

    def get_server_features(self, _source) -> dict[str, Any]:
        return {
            "network": {
                "bandwidth-limit": self.bandwidth_limit or 0,
            }
        }

    def _process_connection_data(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if ss:
            ss.update_connection_data(packet.get_dict(1))

    def _process_bandwidth_limit(self, proto, packet: Packet) -> None:
        log("_process_bandwidth_limit(%s, %s)", proto, packet)
        ss = self.get_server_source(proto)
        if not ss:
            return
        bandwidth_limit = packet.get_u64(1)
        if (self.bandwidth_limit and bandwidth_limit >= self.bandwidth_limit) or bandwidth_limit <= 0:
            bandwidth_limit = self.bandwidth_limit or 0
        if ss.bandwidth_limit == bandwidth_limit:
            # unchanged
            log("bandwidth limit unchanged: %s", std_unit(bandwidth_limit))
            return
        if bandwidth_limit < MIN_BANDWIDTH_LIMIT:
            log.warn("Warning: bandwidth limit requested is too low (%s)", std_unit(bandwidth_limit))
            bandwidth_limit = MIN_BANDWIDTH_LIMIT
        if bandwidth_limit >= MAX_BANDWIDTH_LIMIT:
            log("bandwidth limit over maximum, using no-limit instead")
            bandwidth_limit = 0
        ss.bandwidth_limit = bandwidth_limit
        # we can't assume to have a full ClientConnection object:
        client_id = getattr(ss, "counter", "")
        if bandwidth_limit == 0:
            log.info("bandwidth-limit restrictions removed for client %s", client_id)
        else:
            log.info("bandwidth-limit changed to %sbps for client %s", std_unit(bandwidth_limit), client_id)

    def init_packet_handlers(self) -> None:
        self.add_packets(
            "connection-data", "bandwidth-limit",
        )
