# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.server.subsystem.stub import StubServerMixin
from xpra.net.common import Packet
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("network", "ping")

GLib = gi_import("GLib")


class PingServer(StubServerMixin):
    """
    Adds ping handling
    """

    def __init__(self):
        self.pings = False
        self.ping_timer: int = 0

    def init(self, opts) -> None:
        self.pings = opts.pings

    def setup(self) -> None:
        if self.pings > 0:
            self.ping_timer = GLib.timeout_add(1000 * self.pings, self.send_ping)

    def cleanup(self) -> None:
        pt = self.ping_timer
        if pt:
            self.ping_timer = 0
            GLib.source_remove(pt)

    def get_info(self, _source=None) -> dict[str, Any]:
        return {
            "pings": self.pings,
        }

    def get_server_features(self, _source) -> dict[str, Any]:
        return {}

    def send_ping(self) -> bool:
        from xpra.server.source.bandwidth import BandwidthConnection
        for ss in self._server_sources.values():
            if ss.suspended or ss.is_closed() or not ss.startup_completed:
                continue
            if isinstance(ss, BandwidthConnection):
                ss.ping()
        return True

    def _process_ping_echo(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if ss:
            ss.process_ping_echo(packet)

    def _process_ping(self, proto, packet: Packet) -> None:
        time_to_echo = packet.get_u64(1)
        sid = ""
        if len(packet) >= 4:
            sid = packet.get_str(3)
        ss = self.get_server_source(proto)
        if ss:
            ss.process_ping(time_to_echo, sid)

    def init_packet_handlers(self) -> None:
        self.add_packets(
            "ping", "ping_echo",
        )
