# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from random import random
from queue import SimpleQueue
from typing import Any
from collections.abc import Callable, Sequence

from aioquic.h3.connection import H3Connection
from aioquic.h3.events import DataReceived, DatagramReceived, H3Event
from aioquic.h3.exceptions import H3Error
from aioquic.quic.packet import QuicErrorCode

from xpra.exit_codes import ExitCode
from xpra.net.aio.thread import get_threaded_loop
from xpra.net.bytestreams import Connection
from xpra.net.quic.common import aioquic_version_info, binary_headers, override_aioquic_logger
from xpra.net.quic.congestion import get_congestion_control
from xpra.util.str_fn import Ellipsizer, memoryview_to_bytes
from xpra.util.version import vtrim
from xpra.util.env import envbool
from xpra.net.packet_type import AUDIO_DATA
from xpra.log import Logger

log = Logger("quic")

# the packet types we want to send as datagrams, if the peer accepts them:
DATAGRAM_PACKET_TYPES = tuple(x.strip() for x in os.environ.get(
    "XPRA_QUIC_DATAGRAM_PACKET_TYPES",
    AUDIO_DATA,
).split(",") if x.strip())

# for testing loss tolerance: the percentage of outgoing datagrams to discard
DATAGRAM_DROP_PCT = float(os.environ.get("XPRA_QUIC_DATAGRAM_DROP_PCT", "0"))

if envbool("XPRA_QUIC_LOGGER", True):
    override_aioquic_logger()


class XpraQuicConnection(Connection):
    # packets of these types are sent as datagrams, if they fit,
    # empty until negotiated with the peer (see `set_remote_datagram_packet_types`):
    datagram_packet_types: tuple[str, ...] = ()

    def __init__(self, connection: H3Connection, stream_id: int, transmit: Callable[[], None],
                 host: str, port: int, socktype="wss", info=None, options=None):
        Connection.__init__(self, (host, port), socktype, info=info, options=options)
        self.socktype_wrapped = "quic"
        self.datagram = True
        self.connection: H3Connection = connection
        # HTTP streams on the same QUIC connection share this controller and its statistics.
        self.congestion_control = get_congestion_control(connection.quic_connection)
        self.read_queue: SimpleQueue[bytes] = SimpleQueue()
        # datagrams are independent records, they must never be mixed with the stream data,
        # until something handles them (see `datagram_received`), they are dropped:
        self.datagrams_dropped: int = 0
        # datagram packets too big to be sent as datagrams, sent on the stream instead:
        self.datagram_fallbacks: int = 0
        # datagram packets sent on the stream because no datagram can be sent,
        # ie: the peer's aioquic does not enable HTTP/3 datagrams:
        self.datagrams_unavailable: int = 0
        # outgoing datagrams we have discarded on purpose (see `DATAGRAM_DROP_PCT`):
        self.datagrams_discarded: int = 0
        self.stream_id: int = stream_id
        self.transmit: Callable[[], None] = transmit
        self.accepted: bool = False
        self.closed: bool = False
        log("QUIC congestion controller for %s: %s", self, self.congestion_control)

    def __repr__(self):
        return f"XpraQuicConnection<{self.socktype}:{self.stream_id}>"

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        qinfo = {
            "read-queue": self.read_queue.qsize(),
            "datagrams-dropped": self.datagrams_dropped,
            "datagram-fallbacks": self.datagram_fallbacks,
            "datagrams-unavailable": self.datagrams_unavailable,
            "datagrams-discarded": self.datagrams_discarded,
            "stream-id": self.stream_id,
            "datagram-packet-types": self.datagram_packet_types,
            "accepted": self.accepted,
            "closed": self.closed,
            "aioquic": vtrim(aioquic_version_info),
        }
        config = self.connection.quic_connection.configuration
        qinfo |= {
            "alpn-protocols": config.alpn_protocols,
            "idle-timeout": config.idle_timeout,
            "client": config.is_client,
            "max-data": config.max_data,
            "max-stream-data": config.max_stream_data,
            "server-name": config.server_name or "",
        }
        if self.congestion_control:
            qinfo["congestion"] = self.congestion_control.get_info()
        info["quic"] = qinfo
        return info

    def http_event_received(self, event: H3Event) -> None:
        log("quic:http_event_received(%s)", Ellipsizer(event))
        if self.closed:
            return
        if isinstance(event, DataReceived):
            self.read_queue.put(event.data)
        elif isinstance(event, DatagramReceived):
            self.datagram_received(event.data)
        else:
            log.warn(f"Warning: unhandled websocket http event {event}")

    def datagram_received(self, data: bytes) -> None:
        # called from the asyncio loop thread
        self.datagrams_dropped += 1
        log("datagram_received(%i bytes) dropped", len(data))

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
        self.connection.quic_connection.close(code)

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
        stream_id = self.stream_id
        log("quic.stream_write(%s, %s) using stream id %s", Ellipsizer(buf), packet_type, stream_id)

        def do_write() -> None:
            # aioquic is not thread safe, this runs in the asyncio loop thread
            if self.closed:
                log(f"connection is already closed, packet {packet_type} dropped")
                return
            try:
                # decide here, so the datagram capacity cannot change before it is used:
                if self.use_datagram(data, packet_type):
                    self.do_write_datagram(data)
                else:
                    self.do_write(stream_id, data)
                self.transmit()
            except H3Error:
                if self.closed or self.connection.quic_connection.is_closing():
                    log(f"connection is already closed, packet {packet_type} dropped")
                    return
                raise

        get_threaded_loop().call(do_write)
        return len(buf)

    def use_datagram(self, data: bytes, packet_type: str) -> bool:
        """ called from the asyncio loop thread """
        if packet_type not in self.datagram_packet_types:
            return False
        max_size = self.get_max_datagram_size()
        if not max_size:
            self.datagrams_unavailable += 1
            log("%r packet sent on the stream, no datagram can be sent", packet_type)
            if self.datagrams_unavailable == 1:
                log.info(f"datagrams cannot be sent on this connection, using the stream for {packet_type!r} packets")
            return False
        if len(data) > max_size:
            self.datagram_fallbacks += 1
            log("%r packet too big for a datagram: %i bytes, maximum is %i", packet_type, len(data), max_size)
            if self.datagram_fallbacks == 1:
                log.warn(f"Warning: {packet_type!r} packet is too big to be sent as a datagram")
                log.warn(f" {len(data)} bytes, the maximum is {max_size}, using the stream instead")
            return False
        log("%r packet sent as a datagram for stream id %s", packet_type, self.stream_id)
        return True

    def do_write(self, stream_id: int, data: bytes) -> None:
        self.connection.send_data(stream_id=stream_id, data=data, end_stream=self.closed)
        self.output_bytecount += len(data)
        self.output_writecount += 1

    def set_remote_datagram_packet_types(self, remote_types: Sequence[str]) -> None:
        """ only send the packet types the peer accepts as datagrams """
        self.datagram_packet_types = tuple(x for x in DATAGRAM_PACKET_TYPES if x in remote_types)
        log("set_remote_datagram_packet_types(%s) local=%s, using %s",
            remote_types, DATAGRAM_PACKET_TYPES, self.datagram_packet_types)

    def do_write_datagram(self, data: bytes) -> None:
        if DATAGRAM_DROP_PCT > 0 and random() * 100 < DATAGRAM_DROP_PCT:
            self.datagrams_discarded += 1
            log("datagram discarded: %i bytes", len(data))
            return
        self.connection.send_datagram(self.stream_id, data=data)
        self.output_bytecount += len(data)
        self.output_writecount += 1

    def get_max_datagram_size(self) -> int:
        """
        The largest payload we can send as a single datagram, 0 if datagrams cannot be used.
        aioquic does not fragment datagrams, and refuses the ones which do not fit in a packet.
        """
        # `None` when no datagram can be sent for the stream: until both endpoints have enabled datagrams
        # and the headers were sent, and once the stream or the connection is closing:
        return self.connection.get_datagram_capacity(self.stream_id) or 0

    def read(self, n: int) -> bytes:
        log("quic.read(%s)", n)
        data = self.read_queue.get()
        self.input_bytecount += len(data)
        self.input_readcount += 1
        return data

    def handshake_failed(self, exit_code: ExitCode, message: str) -> None:
        # Called by the client-side handshake watcher when the QUIC/TLS handshake
        # fails after a fast-open transmit. Records the exit code on the connection
        # (consumed by the client's connection-lost handler) and unblocks any
        # pending read() with EOF so the existing close path runs.
        log(f"quic.handshake_failed({exit_code}, {message!r})")
        if self.error == ExitCode.OK:
            self.error = exit_code
        self.closed = True
        self.read_queue.put(b"")
