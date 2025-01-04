# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Callable, Sequence

from aioquic.h3.events import HeadersReceived, H3Event
from aioquic.h3.exceptions import NoAvailablePushIDError
from aioquic.quic.packet import QuicErrorCode

from xpra.net.bytestreams import pretty_socket
from xpra.net.quic.connection import XpraQuicConnection
from xpra.net.quic.common import SERVER_NAME, http_date, binary_headers
from xpra.net.websockets.header import close_packet
from xpra.util.env import first_time
from xpra.util.str_fn import Ellipsizer, std
from xpra.log import Logger

log = Logger("quic")

# can be used to use substreams based on packet prefix: sound,webcam,draw
SUBSTREAM_PACKET_TYPES = tuple(x.strip() for x in os.environ.get(
    "XPRA_QUIC_SUBSTREAM_PACKET_TYPES",
    ""
).split(",") if x.strip())


def filterpath(path: str) -> str:
    return std(path, "-+=&;%@._/")


# SUBSTREAM_PACKET_LOSS_PCT = envint("XPRA_QUIC_SUBSTREAM_PACKET_LOSS_PCT", 0)


class ServerWebSocketConnection(XpraQuicConnection):
    def __init__(self, connection, scope: dict,
                 stream_id: int, transmit: Callable[[], None]) -> None:
        super().__init__(connection, stream_id, transmit, "", 0, "wss", info=None, options=None)
        self.scope: dict = scope
        self._packet_type_streams: dict[str, int] = {}
        self._use_substreams = bool(SUBSTREAM_PACKET_TYPES)

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

    def get_packet_stream_id(self, packet_type: str) -> int:
        if self.closed or not self._use_substreams or not packet_type:
            return self.stream_id
        if not any(packet_type.startswith(x) for x in SUBSTREAM_PACKET_TYPES):
            return self.stream_id
        # ie: "sound-data" -> "sound"
        stream_type = packet_type.split("-", 1)[0]
        stream_id = self._packet_type_streams.get(stream_type)
        if stream_id is not None:
            # already allocated substream:
            return stream_id
        # allocate a new one and record it
        # (even if it fails, so we don't retry to allocate it again and again):
        stream_id = self.allocate_new_stream_id(stream_type) or self.stream_id
        self._packet_type_streams[stream_type] = stream_id
        return stream_id

    def scopestr(self, key: str, default: str, values: Sequence[str] = ()) -> str:
        value = self.scope.get(key, default)
        if values and value not in values:
            raise ValueError(f"invalid value for {key!r}: {value!r}")
        return value

    def allocate_new_stream_id(self, stream_type: str) -> int:
        log(f"allocate_new_stream_id({stream_type!r})")
        # should use more "correct" values here
        # (we don't need those headers,
        # but the client would drop the packet without them..)
        headers = binary_headers({
            ":method": self.scopestr("method", "CONNECT", ("CONNECT", "CONNECT-UDP")),
            ":scheme": self.scopestr("scheme", "wss", ("wss", "https")),
            ":authority": self.scope.get("transport-info", {}).get("sockname", ("localhost", ))[0],
            ":path": filterpath(self.scopestr("path", "/")),
        })
        try:
            stream_id = self.connection.send_push_promise(self.stream_id, headers)
        except NoAvailablePushIDError:
            log(f"unable to allocate new stream-id using {self.stream_id} and {headers}", exc_info=True)
            if first_time("quic-no-push-id"):
                log.warn(f"Warning: unable to allocate a new stream-id for {stream_type!r}")
            else:
                # more than one error, stop trying:
                self._use_substreams = False
            return 0
        log.info(f"new stream: {stream_id} for {stream_type!r} with headers={headers}")
        self.send_headers(stream_id=stream_id, headers={
            ":status": 200,
            "substream": self.stream_id,
            "stream-type": stream_type,
        })
        return stream_id
