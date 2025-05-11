# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.net.glib_handler import GLibPacketHandler
from xpra.client.base.stub import StubClientMixin
from xpra.net.common import Packet


class GLibClient(GLibPacketHandler, StubClientMixin):
    """
    Ensures that a `GLibPacketHandler` can be used as a regular client mixin module,
    by simply extending `StubClientMixin` which provides default methods.

    Also, the client packet handlers don't need the `proto` argument,
    so `call_packet_handler` is overriden so we can skip sending it.
    """

    def call_packet_handler(self, handler: Callable[[Packet], []], proto, packet: Packet) -> None:
        handler(packet)
