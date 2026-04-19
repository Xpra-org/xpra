# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.objects import typedict
from xpra.net.common import PacketElement, BACKWARDS_COMPATIBLE
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("command")


class EventConnection(StubClientConnection):

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        if BACKWARDS_COMPATIBLE and "events" in caps.strtupleget("wants"):
            return True
        return caps.boolget("events")

    def send_server_event(self, event_type: str, *args: PacketElement) -> None:
        if self.hello_sent:
            self.send_more("server-event", event_type, *args)
