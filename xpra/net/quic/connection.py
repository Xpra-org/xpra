# This file is part of Xpra.
# Copyright (C) 2022-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from queue import Queue
from typing import Callable, Union, Dict, Any

from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import DataReceived, DatagramReceived, H3Event

from xpra.net.quic.asyncio_thread import get_threaded_loop
from xpra.net.bytestreams import Connection
from xpra.net.websockets.header import close_packet
from xpra.net.quic.common import binary_headers, override_aioquic_logger
from xpra.util import ellipsizer, envbool
from xpra.os_util import memoryview_to_bytes
from xpra.log import Logger
log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]

#DATAGRAM_PACKET_TYPES = os.environ.get("XPRA_QUIC_DATAGRAM_PACKET_TYPES", "pointer,pointer-button").split(",")
DATAGRAM_PACKET_TYPES = tuple(x.strip() for x in os.environ.get("XPRA_QUIC_DATAGRAM_PACKET_TYPES", "").split(",") if x.strip())

if envbool("XPRA_QUIC_LOGGER", True):
    override_aioquic_logger()


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

    def get_info(self) -> Dict[str,Any]:
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
        log("quic:http_event_received(%s)", ellipsizer(event))
        if self.closed:
            return
        if isinstance(event, (DataReceived, DatagramReceived)):
            self.read_queue.put(event.data)
        else:
            log.warn(f"Warning: unhandled websocket http event {event}")

    def close(self):
        log("quic.close()")
        if not self.closed:
            try:
                self.send_close()
            finally:
                self.closed = True
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

    def write(self, buf, packet_type=None) -> int:
        log("quic.write(%s, %s)", ellipsizer(buf), packet_type)
        return self.stream_write(buf, packet_type)

    def stream_write(self, buf, packet_type):
        data = memoryview_to_bytes(buf)
        if not packet_type:
            log.warn(f"Warning: missing packet type for {data}")
        if packet_type in DATAGRAM_PACKET_TYPES:
            self.connection.send_datagram(flow_id=self.stream_id, data=data)
            log(f"sending {packet_type} using datagram")
            return len(buf)
        stream_id = self.get_packet_stream_id(packet_type)
        log("quic.stream_write(%s, %s) using stream id %s",
            ellipsizer(buf), packet_type, stream_id)
        def do_write():
            try:
                self.connection.send_data(stream_id=stream_id, data=data, end_stream=self.closed)
                self.transmit()
            except AssertionError:
                if self.closed:
                    log("connection is already closed, packet {packet_type} dropped")
                    return
                raise
        get_threaded_loop().call(do_write)
        return len(buf)

    def get_packet_stream_id(self, packet_type):
        return self.stream_id


    def read(self, n):
        log("quic.read(%s)", n)
        return self.read_queue.get()
