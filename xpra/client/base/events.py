# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet, packet_handler
from xpra.client.base.stub import StubClientSubsystem
from xpra.net.packet_type import EVENTS
from xpra.log import Logger

log = Logger("events")


class Events(StubClientSubsystem):
    """
    Receives server events
    """
    __slots__ = ()
    PREFIX = "events"

    def get_caps(self) -> dict[str, Any]:
        return {"events": True}

    # run directly from the network thread:
    @packet_handler(EVENTS)
    @staticmethod
    def _process_events(packet: Packet) -> None:
        log(": ".join(str(x) for x in packet[1:]))
