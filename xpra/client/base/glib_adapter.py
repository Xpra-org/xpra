# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.dispatch import PacketDispatcher
from xpra.client.base.stub import StubClientMixin
from xpra.net.common import Packet, PacketHandlerType

from xpra.os_util import gi_import

GLib = gi_import("GLib")


class GLibClient(PacketDispatcher, StubClientMixin):
    """
    Ensures that a `GLibPacketHandler` can be used as a regular client mixin module,
    by simply extending `StubClientMixin` which provides default methods.

    Also, the client packet handlers don't need the `proto` argument,
    so `call_packet_handler` is overriden so we can skip sending it.
    """

    def call_packet_handler(self, main: bool, handler: PacketHandlerType, proto, packet: Packet) -> None:
        def call() -> None:
            handler(packet)
        if main:
            GLib.idle_add(call)
        else:
            call()
