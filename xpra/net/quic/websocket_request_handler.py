# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
from email.utils import formatdate
from typing import Callable, Dict

from aioquic.h3.events import DataReceived, HeadersReceived, H3Event

from xpra.net.quic.connection import XpraWebSocketConnection
from xpra.net.quic.common import SERVER_NAME
from xpra.util import ellipsizer
from xpra.log import Logger
log = Logger("quic")


class ServerWebSocketConnection(XpraWebSocketConnection):
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
        if isinstance(event, DataReceived):
            self.read_queue.put(event.data)
        elif isinstance(event, HeadersReceived):
            subprotocols = self.scope.get("subprotocols", ())
            if "xpra" not in subprotocols:
                log.warn(f"Warning: unsupported websocket subprotocols {subprotocols}")
                self.close()
                return
            log.info("websocket request at %s", self.scope.get("path", "/"))
            self.send_accept()
        else:
            log.warn(f"Warning: unhandled websocket http event {event}")

    def send_accept(self):
        self.accepted = True
        headers = [
            (b":status", b"200"),
            (b"server", SERVER_NAME.encode()),
            (b"date", formatdate(time.time(), usegmt=True).encode()),
            (b"sec-websocket-protocol", b"xpra"),
            ]
        self.connection.send_headers(stream_id=self.stream_id, headers=headers)
        self.transmit()
