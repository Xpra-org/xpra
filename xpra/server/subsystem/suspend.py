# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.server.subsystem.stub import StubServerMixin
from xpra.common import NotificationID
from xpra.net.common import Packet
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("events")

NOTIFY_SUSPEND_EVENTS = envbool("XPRA_NOTIFY_SUSPEND_EVENTS", True)

NOTIFY_MESSAGE_TITLE = "Server Suspending"
NOTIFY_MESSAGE_BODY = "This Xpra server is going to suspend,\nthe connection is likely to be interrupted soon."


class SuspendServer(StubServerMixin):
    """
    Handle suspend and resume event messages from the client
    """

    def _process_suspend(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        log("suspend(%s) source=%s", packet[1:], ss)
        if ss:
            ss.emit("suspend")
        if NOTIFY_SUSPEND_EVENTS:
            for source in self._server_sources.values():
                source.may_notify(NotificationID.IDLE, NOTIFY_MESSAGE_TITLE, NOTIFY_MESSAGE_BODY,
                                  expire_timeout=10 * 1000, icon_name="shutdown")

    def _process_resume(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        log("resume(%s) source=%s", packet[1:], ss)
        if ss:
            ss.emit("resume")

    def init_packet_handlers(self) -> None:
        self.add_packets(
            "suspend", "resume",
            main_thread=True,
        )
