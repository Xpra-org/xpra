# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("bell")


class BellServer(StubSubsystem):
    """
    Base class for servers that forward bell events to their clients.

    Backend specific subclasses (X11, wayland) hook into whatever bell
    event source their display server provides and call `send_bell`.
    """
    __slots__ = ("bell",)
    PREFIX = "bell"
    toggle_features = ("bell",)

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.bell = False

    def init(self, opts) -> None:
        self.bell = opts.bell
        log(f"bell={opts.bell}")

    def get_caps(self, source) -> dict[str, Any]:
        # Note: don't just call self.get_info() to get rid of linter warnings,
        # this is not safe as it will call it on the subclass!
        return {
            "bell": self.bell,
        }

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "bell": self.bell,
        }

    def _process_bell_set(self, proto, packet: Packet) -> None:
        assert self.bell, "cannot toggle send_bell: the feature is disabled"
        if ss := self.get_server_source(proto):
            ss.window_bell = packet.get_bool(1)

    def send_bell(self, wid=0, device=0, percent=100, pitch=0, duration=0,
                  bell_class=0, bell_id=0, bell_name="") -> None:
        log("send_bell%s bell=%s", (wid, device, percent, pitch, duration, bell_class, bell_id, bell_name), self.bell)
        if not self.bell:
            return
        for ss in self.server.window_sources():
            ss.bell(wid, device, percent, pitch, duration, bell_class, bell_id, bell_name)

    def init_packet_handlers(self) -> None:
        if self.bell:
            self.add_packets("bell-set", main_thread=True)
            self.add_legacy_alias("set-bell", "bell-set")
