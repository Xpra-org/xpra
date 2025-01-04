# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from queue import SimpleQueue
from typing import Union, Any
from collections.abc import Callable

from aioquic import __version__ as aioquic_version
from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import DataReceived, DatagramReceived, H3Event
from aioquic.quic.packet import QuicErrorCode

from xpra.net.quic.asyncio_thread import get_threaded_loop
from xpra.net.bytestreams import Connection
from xpra.net.quic.common import binary_headers, override_aioquic_logger
from xpra.util.str_fn import Ellipsizer, memoryview_to_bytes
from xpra.util.version import parse_version, vtrim
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]

DATAGRAM_PACKET_TYPES = tuple(x.strip() for x in os.environ.get(
    "XPRA_QUIC_DATAGRAM_PACKET_TYPES",
    ""
).split(",") if x.strip())

if envbool("XPRA_QUIC_LOGGER", True):
    override_aioquic_logger()


aioquic_version_info = parse_version(aioquic_version)


class XpraQuicConnection(Connection):
    def __init__(self, connection: HttpConnection, stream_id: int, transmit: Callable[[], None],
                 host: str, port: int, socktype="wss", info=None, options=None) -> None:
        Connection.__init__(self, (host, port), socktype, info=info, options=options)
        self.socktype_wrapped = "quic"
        self.connection: HttpConnection = connection
        self.read_queue: SimpleQueue[bytes] = SimpleQueue()
        self.stream_id: int = stream_id
        self.transmit: Callable[[], None] = transmit
        self.accepted: bool = False
        self.closed: bool = False

    def __repr__(self):
        return f"XpraQuicConnection<{self.socktype}:{self.stream_id}>"

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        qinfo = {
            "read-queue": self.read_queue.qsize(),
            "stream-id": self.stream_id,
            "accepted": self.accepted,
            "closed": self.closed,
            "aioquic": vtrim(aioquic_version_info),
        }
        quic = getattr(self.connection, "_quic", None)
        if quic:
            config = quic.configuration
            qinfo |= {
                "alpn-protocols": config.alpn_protocols,
                "idle-timeout": config.idle_timeout,
                "client": config.is_client,
                "max-data": config.max_data,
                "max-stream-data": config.max_stream_data,
                "server-name": config.server_name or "",
            }
        info["quic"] = qinfo
        return info

    def http_event_received(self, event: H3Event) -> None:
        log("quic:http_event_received(%s)", Ellipsizer(event))
        if self.closed:
            return
        if isinstance(event, (DataReceived, DatagramReceived)):
            self.read_queue.put(event.data)
        else:
            log.warn(f"Warning: unhandled websocket http event {event}")

    def close(self, code=QuicErrorCode.NO_ERROR, reason="closing") -> None:
        log(f"quic.close({code}, {reason})")
        if not self.closed:
            try:
                self.send_close(code, reason)
            finally:
                self.closed = True
        Connection.close(self)

    def send_close(self, code=QuicErrorCode.NO_ERROR, reason="") -> None:
        # we just close the quic connection here
        # subclasses may also override this method to send close messages specific to the protocol
        # ie: WebSocket and WebTransport 'close' frames
        quic = getattr(self.connection, "_quic", None)
        if not quic:
            return
        if aioquic_version_info >= (1, 2):
            # we can send the error code and message
            quic.close(code)
        else:
            quic.close()

    def send_headers(self, stream_id: int, headers: dict) -> None:
        self.connection.send_headers(
            stream_id=stream_id,
            headers=binary_headers(headers),
            end_stream=self.closed)

    def write(self, buf, packet_type: str = "") -> int:
        log("quic.write(%s, %r)", Ellipsizer(buf), packet_type)
        return self.stream_write(buf, packet_type)

    def stream_write(self, buf, packet_type: str) -> int:
        data = memoryview_to_bytes(buf)
        if not packet_type:
            log.warn(f"Warning: missing packet type for {data}")
        if packet_type in DATAGRAM_PACKET_TYPES:
            self.connection.send_datagram(self.stream_id, data=data)
            log(f"sending {packet_type!r} using datagram")
            return len(buf)
        stream_id = self.get_packet_stream_id(packet_type)
        log("quic.stream_write(%s, %s) using stream id %s", Ellipsizer(buf), packet_type, stream_id)

        def do_write() -> None:
            if self.closed:
                log(f"connection is already closed, packet {packet_type} dropped")
                return
            try:
                self.do_write(stream_id, data)
                self.transmit()
            except AssertionError:
                if self.closed:
                    log(f"connection is already closed, packet {packet_type} dropped")
                    return
                raise

        get_threaded_loop().call(do_write)
        return len(buf)

    def do_write(self, stream_id: int, data: bytes) -> None:
        self.connection.send_data(stream_id=stream_id, data=data, end_stream=self.closed)

    def get_packet_stream_id(self, packet_type: str) -> int:
        return self.stream_id

    def read(self, n: int) -> bytes:
        log("quic.read(%s)", n)
        return self.read_queue.get()
