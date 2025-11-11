# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import SimpleQueue
from typing import Any
from collections.abc import Callable

from aioquic.h3.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    WebTransportStreamDataReceived,
)
from aioquic.quic.packet import QuicErrorCode

from xpra.net.bytestreams import pretty_socket
from xpra.net.quic.connection import XpraQuicConnection, HttpConnection
from xpra.net.quic.common import SERVER_NAME, http_date
from xpra.log import Logger

log = Logger("quic")


class ServerWebTransportConnection(XpraQuicConnection):
    def __init__(self, connection: HttpConnection, scope: dict, stream_id: int, transmit: Callable[[], None]):
        super().__init__(connection, stream_id, transmit, "", 0, "webtransport")
        self.http_event_queue: SimpleQueue[DataReceived] = SimpleQueue()
        # self.read_datagram_queue = SimpleQueue()
        self.scope = scope

    def __repr__(self):
        try:
            return f"QuicConnection({pretty_socket(self.endpoint)}, {self.stream_id})"
        except AttributeError:
            return f"WebTransportHandler<{self.stream_id}>"

    def http_event_received(self, event: H3Event) -> None:
        log("wt.http_event_received(%s) closed=%s, accepted=%s", event, self.closed, self.accepted)
        if self.closed:
            return
        if self.accepted:
            if isinstance(event, DatagramReceived):
                # self.read_datagram_queue.put(event.data)
                log("datagram ignored")
            elif isinstance(event, WebTransportStreamDataReceived):
                if event.stream_id != self.stream_id:
                    log(f"switching to stream_id={event.stream_id}")
                    self.stream_id = event.stream_id
                self.read_queue.put(event.data)
        else:
            self.accepted = True
            self.send_accept()
            self.transmit()

    def send_accept(self) -> None:
        headers: dict[str, Any] = {
            ":status": "200",
            "server": SERVER_NAME,
            "date": http_date(),
            "sec-webtransport-http3-draft": "draft02",
        }
        assert self.stream_id == 0
        self.send_headers(self.stream_id, headers)
        self.transmit()

    def send_close(self, code=QuicErrorCode.NO_ERROR, reason="") -> None:
        if not self.accepted:
            httpcode = 200 if code == QuicErrorCode.NO_ERROR else 500
            self.send_http_close(httpcode, reason)
        super().send_close(code, reason)

    def send_http_close(self, code: int = 500, reason: str = "") -> None:
        log(f"send_http_close({code}, {reason!r})")
        self.send_headers(0, {":status": code})
        self.transmit()

    def do_write(self, stream_id: int, data: bytes) -> None:
        log("wt.do_write(%i, %i bytes)", stream_id, len(data))
        self.connection._quic.send_stream_data(stream_id=stream_id, data=data, end_stream=self.closed)

    def send_datagram(self, data: bytes) -> None:
        log("send_datagram(%i bytes)", len(data))
        self.connection.send_datagram(self.stream_id, data=data)
        self.transmit()

    def read(self, n: int) -> bytes:
        log("WebTransportHandler.read(%s)", n)
        return self.read_queue.get()
