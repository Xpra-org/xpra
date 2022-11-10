# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import Queue
from typing import Callable, Union

from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import H3Event

from xpra.net.bytestreams import Connection
from xpra.net.websockets.header import close_packet
from xpra.util import ellipsizer
from xpra.os_util import memoryview_to_bytes
from xpra.log import Logger
log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]


class XpraWebSocketConnection(Connection):
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
        return f"XpraWebSocketConnection<{self.stream_id}>"

    def http_event_received(self, event: H3Event) -> None:
        raise NotImplementedError()

    def close(self):
        log("XpraWebSocketConnection.close()")
        if not self.closed:
            self.send_close(1000)
        Connection.close(self)

    def send_close(self, code : int = 1000, reason : str = ""):
        if self.accepted:
            data = close_packet(code, reason)
            self.connection.send_data(stream_id=self.stream_id, data=data, end_stream=True)
        else:
            self.connection.send_headers(stream_id=self.stream_id, headers=[(b":status", str(code).encode())])
        self.closed = True
        self.transmit()

    def write(self, buf):
        log("XpraWebSocketConnection.write(%s)", ellipsizer(buf))
        data = memoryview_to_bytes(buf)
        self.connection.send_data(stream_id=self.stream_id, data=data, end_stream=self.closed)
        self.transmit()
        return len(buf)

    def read(self, n):
        log("XpraWebSocketConnection.read(%s)", n)
        return self.read_queue.get()
