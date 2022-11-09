#Copyright (c) 2018-2019 Jeremy Lainé.
#All rights reserved.
#
#Redistribution and use in source and binary forms, with or without
#modification, are permitted provided that the following conditions are met:
#
#    * Redistributions of source code must retain the above copyright notice,
#      this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright notice,
#      this list of conditions and the following disclaimer in the documentation
#      and/or other materials provided with the distribution.
#    * Neither the name of aioquic nor the names of its contributors may
#      be used to endorse or promote products derived from this software without
#      specific prior written permission.

#THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
#ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
#WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
#FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
#DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
#CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
#OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
import time
import struct
from queue import Queue
from email.utils import formatdate
from typing import Callable, Dict, Union

from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import DataReceived, HeadersReceived, H3Event

from xpra.net.websockets.mask import hybi_mask  # pylint: disable=no-name-in-module
from xpra.net.websockets.header import encode_hybi_header
from xpra.net.quic.common import SERVER_NAME
from xpra.util import ellipsizer
from xpra.log import Logger
log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]


class WebSocketHandler:
    def __init__(self, connection: HttpConnection, scope: Dict, stream_id: int, transmit: Callable[[], None]) -> None:
        self.closed = False
        self.connection = connection
        self.data_queue: Queue[bytes] = Queue()
        self.scope = scope
        self.stream_id = stream_id
        self.transmit = transmit
        self.accepted : bool = False

    def http_event_received(self, event: H3Event) -> None:
        log("ws:http_event_received(%s)", ellipsizer(event))
        if self.closed:
            return
        if isinstance(event, DataReceived):
            self.data_queue.put(event.data)
        elif isinstance(event, HeadersReceived):
            subprotocols = self.scope.get("subprotocols", ())
            if "xpra" not in subprotocols:
                log.warn(f"Warning: unsupported websocket subprotocols {subprotocols}")
                self.close()
                return
            log.info("websocket request at %s", self.scope.get("path", "/"))
            self.send_accept()


    def close(self):
        if not self.closed:
            self.send_close(1000)

    def receive(self) -> Dict:
        log("ws:receive()")
        return self.data_queue.get()


    def send_accept(self, subprotocol : str = "xpra"):
        self.accepted = True
        headers = [
            (b":status", b"200"),
            (b"server", SERVER_NAME.encode()),
            (b"date", formatdate(time.time(), usegmt=True).encode()),
        ]
        if subprotocol:
            headers.append((b"sec-websocket-protocol", subprotocol.encode()))
        self.connection.send_headers(stream_id=self.stream_id, headers=headers)
        self.transmit()

    def send_close(self, code : int = 1000, reason : str = ""):
        if self.accepted:
            data = struct.pack("!H", code)
            if reason:
                #should validate that encoded data length is less than 125, meh
                data += reason.encode("utf-8")
            header = encode_hybi_header(code, len(data), has_mask=False, fin=True)
            self.connection.send_data(stream_id=self.stream_id, data=header+data, end_stream=True)
        else:
            self.connection.send_headers(stream_id=self.stream_id, headers=[(b":status", str(code).encode())])
        self.closed = True
        self.transmit()

    def send_bytes(self, bdata : bytes):
        mask = os.urandom(4)
        data = hybi_mask(mask, bdata)
        self.connection.send_data(stream_id=self.stream_id, data=data)
        self.transmit()
