# This file is part of Xpra.
# Copyright (C) 2022-2024 Antoine Martin <antoine@xpra.org>
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
from xpra.net.bytestreams import pretty_socket
from xpra.net.quic.connection import XpraQuicConnection, HttpConnection
from xpra.net.quic.common import SERVER_NAME, http_date
from xpra.log import Logger

log = Logger("quic")


class ServerWebTransportConnection(XpraQuicConnection):
    def __init__(self, connection: HttpConnection, scope: dict, stream_id: int, transmit: Callable[[], None]) -> None:
        super().__init__(connection, stream_id, transmit, "", 0, info=None, options=None)
        self.http_event_queue: SimpleQueue[DataReceived] = SimpleQueue()
        # self.read_datagram_queue = SimpleQueue()
        self.scope = scope

    def __repr__(self):
        try:
            return f"QuicConnection({pretty_socket(self.endpoint)}, {self.stream_id})"
        except AttributeError:
            return f"WebTransportHandler<{self.stream_id}>"

    def http_event_received(self, event: H3Event) -> None:
        log.info(f"wt.http_event_received({event}) closed={self.closed}, accepted={self.accepted}")
        if self.closed:
            return
        if self.accepted:
            if isinstance(event, DatagramReceived):
                # self.read_datagram_queue.put(event.data)
                log("datagram ignored")
            elif isinstance(event, WebTransportStreamDataReceived):
                log(f"data for stream_id={event.stream_id}, our stream_id={self.stream_id}")
                if event.stream_id != self.stream_id:
                    self.stream_id = event.stream_id
                    # ensure we can send data on this stream from now on:
                    self.send_headers(self.stream_id, {})
                self.read_queue.put(event.data)
        else:
            self.accepted = True
            self.send_accept()
            # self.connection.create_webtransport_stream()
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

    def send_close(self, code: int = 403, reason: str = "") -> None:
        log(f"send_close({code}, {reason!r})")
        if not self.accepted:
            self.closed = True
            self.send_headers(0, {":status": code})
            self.transmit()

    def send_datagram(self, data: bytes) -> None:
        log(f"send_datagram({len(data)} bytes)")
        self.connection.send_datagram(flow_id=self.stream_id, data=data)
        self.transmit()

    def read(self, n: int) -> bytes:
        log("WebTransportHandler.read(%s)", n)
        return self.read_queue.get()
