# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import Queue
from typing import Callable, Union

from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import DataReceived, H3Event

from xpra.net.bytestreams import Connection
from xpra.net.websockets.header import close_packet
from xpra.net.quic.common import binary_headers
from xpra.util import ellipsizer
from xpra.os_util import memoryview_to_bytes
from xpra.log import Logger
log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]


class XpraQuicConnection(Connection):
    def __init__(self, connection: HttpConnection, stream_id: int, transmit: Callable[[], None],
                 host : str, port : int, info=None, options=None) -> None:
        Connection.__init__(self, (host, port), "wss", info=info, options=options)
        self.socktype_wrapped = "quic"
        self.connection: HttpConnection = connection
        self.read_queue: Queue[bytes] = Queue()
        self.stream_id: int = stream_id
        self.transmit: Callable[[], None] = transmit
        self.accepted : bool = False
        self.closed : bool = False

    def __repr__(self):
        return f"XpraQuicConnection<{self.stream_id}>"

    def get_info(self) -> dict:
        info = super().get_info()
        qinfo = info.setdefault("quic", {})
        quic = getattr(self.connection, "_quic", None)
        if quic:
            config = quic.configuration
            qinfo.update({
                "alpn-protocols" : config.alpn_protocols,
                "idle-timeout"  : config.idle_timeout,
                "client"        : config.is_client,
                "max-data"      : config.max_data,
                "max-stream-data" : config.max_stream_data,
                "server-name"   : config.server_name or "",
                })
        qinfo.update({
            "read-queue"    : self.read_queue.qsize(),
            "stream-id"     : self.stream_id,
            "accepted"      : self.accepted,
            "closed"        : self.closed,
            })
        return info

    def http_event_received(self, event: H3Event) -> None:
        log("ws:http_event_received(%s)", ellipsizer(event))
        if self.closed:
            return
        if isinstance(event, DataReceived):
            self.read_queue.put(event.data)
        else:
            log.warn(f"Warning: unhandled websocket http event {event}")

    def close(self):
        log("XpraQuicConnection.close()")
        if not self.closed:
            self.closed = True
            self.send_close()
        Connection.close(self)

    def send_close(self, code : int = 1000, reason : str = ""):
        if self.accepted:
            data = close_packet(code, reason)
            self.write(data, "close")
        else:
            self.send_headers(self.stream_id, headers={":status" : code})
            self.transmit()

    def send_headers(self, stream_id : int, headers : dict):
        self.connection.send_headers(
            stream_id=stream_id,
            headers=binary_headers(headers),
            end_stream=self.closed)

    def write(self, buf, packet_type=None):
        log("XpraQuicConnection.write(%s, %s)", ellipsizer(buf), packet_type)
        try:
            return self.stream_write(buf, packet_type)
        finally:
            self.transmit()

    def stream_write(self, buf, packet_type):
        if not packet_type:
            log.warn(f"no packet type for {buf}")
        data = memoryview_to_bytes(buf)
        stream_id = self.get_packet_stream_id(packet_type)
        log("XpraQuicConnection.stream_write(%s, %s) using stream id %s",
            ellipsizer(buf), packet_type, stream_id)
        self.connection.send_data(stream_id=stream_id, data=data, end_stream=self.closed)
        return len(buf)

    def get_packet_stream_id(self, packet_type):
        return self.stream_id


    def read(self, n):
        log("XpraQuicConnection.read(%s)", n)
        return self.read_queue.get()
