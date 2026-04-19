# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("events")


class EventsClient(StubClientMixin):
    """
    Receives server events
    """

    def get_caps(self) -> dict[str, Any]:
        return {"events": True}

    @staticmethod
    def _process_server_event(packet: Packet) -> None:
        log(": ".join(str(x) for x in packet[1:]))

    def init_authenticated_packet_handlers(self) -> None:
        # run directly from the network thread:
        self.add_packets("server-event")
