# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.server.subsystem.stub import StubSubsystem
from xpra.net.common import Packet
from xpra.log import Logger

log = Logger("events")


class SuspendServer(StubSubsystem):
    """
    Handle suspend and resume event messages from the client
    """
    __slots__ = ()
    PREFIX = "suspend"

    def _process_suspend(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        # the boolean argument tells us whether we are suspending or resuming:
        suspend = packet.get_bool(1) if len(packet) > 1 else True
        log("suspend(%s) suspend=%s source=%s", packet[1:], suspend, ss)
        if ss:
            ss.emit("suspend" if suspend else "resume")

    def init_packet_handlers(self) -> None:
        self.add_packets("suspend", main_thread=True)
