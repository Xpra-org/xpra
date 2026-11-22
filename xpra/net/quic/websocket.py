# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from aioquic.h3.events import HeadersReceived, H3Event
from aioquic.quic.packet import QuicErrorCode

from xpra.net.common import pretty_socket
from xpra.net.quic.connection import XpraQuicConnection
from xpra.net.quic.common import SERVER_NAME, http_date
from xpra.net.websockets.header import close_packet
from xpra.util.str_fn import Ellipsizer
from xpra.log import Logger

log = Logger("quic")


class ServerWebSocketConnection(XpraQuicConnection):
    def __init__(self, connection, scope: dict,
                 stream_id: int, transmit: Callable[[], None]):
        super().__init__(connection, stream_id, transmit, "", 0, "wss", info=None, options=None)
        self.scope: dict = scope

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info.setdefault("quic", {})["scope"] = self.scope
        return info

    def __repr__(self):
        try:
            return f"QuicConnection({pretty_socket(self.endpoint)}, {self.stream_id})"
        except AttributeError:
            return f"ServerWebSocketConnection<{self.stream_id}>"

    def http_event_received(self, event: H3Event) -> None:
        log("ws:http_event_received(%s)", Ellipsizer(event))
        if self.closed:
            return
        if isinstance(event, HeadersReceived):
            subprotocols = self.scope.get("subprotocols", ())
            if "xpra" not in subprotocols:
                message = f"unsupported websocket subprotocols {subprotocols}"
                log.warn(f"Warning: {message}")
                self.close(QuicErrorCode.APPLICATION_ERROR, message)
                return
            log.info("websocket request at %s", self.scope.get("path", "/"))
            self.accepted = True
            self.send_accept(self.stream_id)
            self.transmit()
            return
        super().http_event_received(event)

    def send_accept(self, stream_id: int) -> None:
        self.send_headers(stream_id=stream_id, headers={
            ":status": 200,
            "server": SERVER_NAME,
            "date": http_date(),
            "sec-websocket-protocol": "xpra",
        })

    def send_close(self, code=QuicErrorCode.NO_ERROR, reason="") -> None:
        log(f"send_close({code}, {reason})")
        wscode = 1000 if code == QuicErrorCode.NO_ERROR else 4000 + int(code)
        self.send_ws_close(wscode, reason)
        super().send_close(code, reason)

    def send_ws_close(self, code: int = 1000, reason: str = "") -> None:
        if self.accepted:
            data = close_packet(code, reason)
            self.write(data, "close")
        else:
            self.send_headers(self.stream_id, headers={":status": code})
            self.transmit()
