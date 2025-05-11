# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.server.subsystem.stub import StubServerMixin
from xpra.net.common import Packet
from xpra.log import Logger

log = Logger("events")


class SuspendServer(StubServerMixin):
    """
    Handle suspend and resume events
    """

    def _process_suspend(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        log("suspend(%s) source=%s", packet[1:], ss)
        if ss:
            ss.suspend()

    def _process_resume(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        log("resume(%s) source=%s", packet[1:], ss)
        if ss:
            ss.resume()

    def init_packet_handlers(self) -> None:
        self.add_packets(
            "suspend", "resume",
            main_thread=True,
        )
