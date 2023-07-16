# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import Queue
from typing import Callable, Dict, Any

from aioquic.h3.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    WebTransportStreamDataReceived,
)
from xpra.net.quic.connection import XpraQuicConnection, HttpConnection
from xpra.net.quic.common import SERVER_NAME, http_date
from xpra.log import Logger
log = Logger("quic")


class WebTransportHandler(XpraQuicConnection):
    def __init__(self, connection: HttpConnection, scope: Dict, stream_id: int, transmit: Callable[[], None]) -> None:
        super().__init__(connection, stream_id, transmit, "", 0, info=None, options=None)
        self.http_event_queue: Queue[DataReceived] = Queue()
        self.read_datagram_queue = Queue()
        self.scope = scope

    def http_event_received(self, event: H3Event) -> None:
        if self.closed:
            return
        if self.accepted:
            if isinstance(event, DatagramReceived):
                self.read_datagram_queue.put(event.data)
            elif isinstance(event, WebTransportStreamDataReceived):
                self.read_queue.put((event.stream_id, event.data))
        else:
            self.http_event_queue.put(event)

    def send_accept(self) -> None:
        self.accepted = True
        headers : Dict[str,Any] = {
            ":status"   : "200",
            "server"    : SERVER_NAME,
            "date"      : http_date(),
            "sec-webtransport-http3-draft" : "draft02",
            }
        self.send_headers(0, headers)
        self.transmit()

    def flush_http_event_queue(self):
        while self.http_event_queue.qsize():
            self.http_event_received(self.http_event_queue.get())

    def send_close(self, code : int = 403, reason : str = ""):
        if not self.accepted:
            self.closed = True
            self.send_headers(0, {":status" : code})
            self.transmit()

    def send_datagram(self, data):
        self.connection.send_datagram(flow_id=self.stream_id, data=data)
        self.transmit()

    def write(self, stream_id : int, data : bytes) -> None:
        self.connection._quic.send_stream_data(stream_id=stream_id, data=data)
        self.transmit()

    def read(self, n):
        log("WebTransportHandler.read(%s)", n)
        return self.read_queue.get()
