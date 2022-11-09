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

import asyncio
import time
from collections import deque
from email.utils import formatdate
from typing import Callable, Deque, Dict, Optional, Union

import wsproto.events

from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import DataReceived, HeadersReceived, H3Event

from xpra.net.quic.common import SERVER_NAME
from xpra.util import ellipsizer
from xpra.log import Logger
log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]


class WebSocketHandler:
    def __init__(self, connection: HttpConnection, scope: Dict, stream_id: int, transmit: Callable[[], None]) -> None:
        self.closed = False
        self.connection = connection
        self.http_event_queue: Deque[DataReceived] = deque()
        self.queue: asyncio.Queue[Dict] = asyncio.Queue()
        self.scope = scope
        self.stream_id = stream_id
        self.transmit = transmit
        self.websocket: Optional[wsproto.Connection] = None
        #self.queue.put_nowait({"type": "websocket.connect"})

    def http_event_received(self, event: H3Event) -> None:
        log("ws:http_event_received(%s)", ellipsizer(event))
        if self.closed:
            return
        if isinstance(event, DataReceived):
            if self.websocket is not None:
                self.websocket.receive_data(event.data)
                for ws_event in self.websocket.events():
                    self.websocket_event_received(ws_event)
            else:
                # delay event processing until we get `websocket.accept`
                # from the ASGI application
                self.http_event_queue.append(event)
        elif isinstance(event, HeadersReceived):
            subprotocols = self.scope.get("subprotocols", ())
            if "xpra" not in subprotocols:
                log.warn(f"Warning: unsupported websocket subprotocols {subprotocols}")
                self.close()
                return
            log.info("websocket request at %s", self.scope.get("path", "/"))
            self.send_accept()


    def websocket_event_received(self, event: wsproto.events.Event) -> None:
        log("ws:websocket_event_received(%s)", ellipsizer(event))
        if isinstance(event, wsproto.events.TextMessage):
            self.queue.put_nowait({"type": "websocket.receive", "text": event.data})
        elif isinstance(event, wsproto.events.Message):
            self.queue.put_nowait({"type": "websocket.receive", "bytes": event.data})
        elif isinstance(event, wsproto.events.CloseConnection):
            self.queue.put_nowait({"type": "websocket.disconnect", "code": event.code})

    def close(self):
        if not self.closed:
            self.send_close(1000)

    async def receive(self) -> Dict:
        log("ws:receive()")
        return await self.queue.get()


    def send_accept(self, subprotocol : str = "xpra"):
        self.websocket = wsproto.Connection(wsproto.ConnectionType.SERVER)
        headers = [
            (b":status", b"200"),
            (b"server", SERVER_NAME.encode()),
            (b"date", formatdate(time.time(), usegmt=True).encode()),
        ]
        if subprotocol:
            headers.append((b"sec-websocket-protocol", subprotocol.encode()))
        self.connection.send_headers(stream_id=self.stream_id, headers=headers)
        # consume backlog
        while self.http_event_queue:
            self.http_event_received(self.http_event_queue.popleft())
        self.transmit()

    def send_close(self, code : int = 403):
        if self.websocket is not None:
            data = self.websocket.send(wsproto.events.CloseConnection(code))
            self.connection.send_data(stream_id=self.stream_id, data=data, end_stream=True)
        else:
            self.connection.send_headers(stream_id=self.stream_id, headers=[(b":status", str(code).encode())])
        self.closed = True
        self.transmit()

    #def send_text(self, text : str):
    #    data = self.websocket.send(wsproto.events.TextMessage(text))
    #    self.connection.send_data(stream_id=self.stream_id, data=data)
    #    self.transmit()

    def send_bytes(self, bdata : bytes):
        #from xpra.net.websockets.mask import hybi_mask
        #mask = os.urandom(4)
        #data = hybi_mask(mask, bdata)
        data = self.websocket.send(wsproto.events.Message(bdata))
        self.connection.send_data(stream_id=self.stream_id, data=data)
        self.transmit()
