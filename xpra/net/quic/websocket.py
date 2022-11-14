# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Callable, Dict

from aioquic.h3.events import HeadersReceived, H3Event

from xpra.net.quic.connection import XpraQuicConnection
from xpra.net.quic.common import SERVER_NAME, http_date
from xpra.util import ellipsizer
from xpra.log import Logger
log = Logger("quic")


class ServerWebSocketConnection(XpraQuicConnection):
    def __init__(self, connection, scope: Dict,
                 stream_id: int, transmit: Callable[[], None]) -> None:
        super().__init__(connection, stream_id, transmit, "", 0, info=None, options=None)
        self.scope: Dict = scope

    def __repr__(self):
        return f"ServerWebSocketConnection<{self.stream_id}>"

    def http_event_received(self, event: H3Event) -> None:
        log("ws:http_event_received(%s)", ellipsizer(event))
        if self.closed:
            return
        if isinstance(event, HeadersReceived):
            subprotocols = self.scope.get("subprotocols", ())
            if "xpra" not in subprotocols:
                log.warn(f"Warning: unsupported websocket subprotocols {subprotocols}")
                self.close()
                return
            log.info("websocket request at %s", self.scope.get("path", "/"))
            self.send_accept()
            return
        super().http_event_received(event)

    def send_accept(self):
        self.accepted = True
        self.send_headers({
            ":status"   : 200,
            "server"    : SERVER_NAME,
            "date"      : http_date(),
            "sec-websocket-protocol" : "xpra",
            })
        self.transmit()
