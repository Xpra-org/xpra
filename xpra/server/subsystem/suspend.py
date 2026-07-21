# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.server.subsystem.stub import StubSubsystem
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
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
        # the boolean argument tells us whether we are suspending or resuming
        # (older clients send a separate `resume` packet, see `_process_resume`):
        suspend = packet.get_bool(1) if len(packet) > 1 else True
        log("suspend(%s) suspend=%s source=%s", packet[1:], suspend, ss)
        if ss:
            ss.emit("suspend" if suspend else "resume")

    def _process_resume(self, proto, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        ss = self.get_server_source(proto)
        log("resume(%s) source=%s", packet[1:], ss)
        if ss:
            ss.emit("resume")

    def init_packet_handlers(self) -> None:
        if BACKWARDS_COMPATIBLE:
            self.add_packets("resume", main_thread=True)
        self.add_packets("suspend", main_thread=True)
