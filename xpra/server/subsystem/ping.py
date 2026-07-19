# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.server.common import get_sources_by_type
from xpra.server.subsystem.stub import StubSubsystem
from xpra.net.common import Packet
from xpra.log import Logger

log = Logger("network", "ping")


class PingServer(StubSubsystem):
    """
    Adds ping handling
    """
    __slots__ = ("delay", "timer")
    PREFIX = "ping"

    def __init__(self, server):
        super().__init__(server)
        self.delay = False
        self.timer: int = 0

    def init(self, opts) -> None:
        self.delay = opts.pings

    def setup(self) -> None:
        if self.delay > 0:
            self.timer = self.timeout_add(1000 * self.delay, self.send_ping)

    def cleanup(self) -> None:
        if pt := self.timer:
            self.timer = 0
            self.source_remove(pt)

    def get_info(self, _proto) -> dict[str, Any]:
        return self.get_caps(None)

    def get_caps(self, _source) -> dict[str, Any]:
        return {
            PingServer.PREFIX: self.delay,
        }

    def send_ping(self) -> bool:
        from xpra.server.source.ping import PingConnection
        ping_sources = get_sources_by_type(self.server, PingConnection)
        for ss in ping_sources:
            if ss.suspended or ss.is_closed():
                continue
            ss.ping()
        return True

    def _process_ping_echo(self, proto, packet: Packet) -> None:
        if ss := self.get_server_source(proto):
            ss.process_ping_echo(packet)

    def _process_ping(self, proto, packet: Packet) -> None:
        time_to_echo = packet.get_u64(1)
        sid = ""
        if len(packet) >= 4:
            sid = packet.get_str(3)
        if ss := self.get_server_source(proto):
            ss.process_ping(time_to_echo, sid)

    def init_packet_handlers(self) -> None:
        self.add_packets(
            "ping", "ping_echo",
        )
