# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2026 Netflix, Inc.
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

from xpra.net.aio.thread import get_threaded_loop
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
                 host: str, port: int, socktype="wss", info=None, options=None):
        Connection.__init__(self, (host, port), socktype, info=info, options=options)
        self.socktype_wrapped = "quic"
        self.connection: HttpConnection = connection
        self.read_queue: SimpleQueue[bytes] = SimpleQueue()
        self.stream_id: int = stream_id
        self.transmit: Callable[[], None] = transmit
        self.accepted: bool = False
        self.closed: bool = False
        # substream send infrastructure (configured by subclasses)
        self._packet_type_streams: dict[str, int] = {}
        self._substream_ids: set[int] = set()
        self._pending_substreams: set[str] = set()
        self._use_substreams: bool = False
        self._substream_packet_types: tuple[str, ...] = ()
        self._register_substream: Callable | None = None

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
        # process any pending substream allocations (we're on the asyncio loop now)
        if self._pending_substreams:
            pending = list(self._pending_substreams)
            self._pending_substreams.clear()
            log(f"allocating pending substreams: {pending}")
            for stream_type in pending:
                self._allocate_substream(stream_type)
        if stream_id in self._substream_ids:
            # raw QUIC stream — strip WS frame header, bypass H3
            # WS framing is always added by make_wsframe_header (format thread)
            # and stripped here (asyncio thread) to avoid a race between the
            # framing decision and stream routing across threads
            data = self._strip_ws_header(data)
            log(f"substream {stream_id}: writing {len(data)} bytes")
            self.connection._quic.send_stream_data(stream_id=stream_id, data=data, end_stream=self.closed)
        else:
            # main WebSocket stream — use H3 DATA frames
            self.connection.send_data(stream_id=stream_id, data=data, end_stream=self.closed)

    def get_packet_stream_id(self, packet_type: str) -> int:
        if self.closed or not self._use_substreams or not packet_type:
            return self.stream_id
        if not any(packet_type.startswith(x) for x in self._substream_packet_types):
            return self.stream_id
        # ie: "sound-data" -> "sound", "key-action" -> "key"
        stream_type = packet_type.split("-", 1)[0]
        stream_id = self._packet_type_streams.get(stream_type)
        if stream_id is not None:
            # already allocated substream:
            return stream_id
        # reserve the stream type so we don't retry on the next packet;
        # actual allocation happens on the asyncio loop in _allocate_substream()
        self._packet_type_streams[stream_type] = self.stream_id
        self._pending_substreams.add(stream_type)
        return self.stream_id

    def _allocate_substream(self, stream_type: str) -> None:
        """Allocate a raw QUIC stream for a packet type. Must run on the asyncio loop."""
        log(f"_allocate_substream({stream_type!r})")
        quic = self.connection._quic
        try:
            stream_id = quic.get_next_available_stream_id()
        except Exception:
            log(f"unable to allocate new stream-id for {stream_type!r}", exc_info=True)
            log.warn(f"Warning: unable to allocate a new stream-id for {stream_type!r}")
            self._use_substreams = False
            return
        # send type prefix as first bytes (QUIC guarantees in-order per-stream)
        header = f"xpra:{stream_type}\n".encode()
        log(f"sending substream header on stream {stream_id}: {header!r}")
        quic.send_stream_data(stream_id, header)
        self._substream_ids.add(stream_id)
        self._packet_type_streams[stream_type] = stream_id
        log.info(f"new substream {stream_id} for {stream_type!r}")
        if self._register_substream:
            self._register_substream(stream_id, self)

    @staticmethod
    def _strip_ws_header(data: bytes) -> bytes:
        """Strip the WebSocket binary frame header from data."""
        if len(data) < 2 or data[0] != 0x82:
            return data
        length_byte = data[1] & 0x7F
        if length_byte <= 125:
            return data[2:]
        if length_byte == 126:
            return data[4:]
        # length_byte == 127
        return data[10:]

    def read(self, n: int) -> bytes:
        log("quic.read(%s)", n)
        return self.read_queue.get()
