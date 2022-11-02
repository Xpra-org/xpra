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
from typing import Callable, Deque, Dict, List, Optional, Union, cast

import wsproto.events

import aioquic
from aioquic.asyncio import QuicConnectionProtocol
from aioquic.h0.connection import H0_ALPN, H0Connection
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from aioquic.h3.exceptions import NoAvailablePushIDError
from aioquic.quic.events import DatagramFrameReceived, ProtocolNegotiated, QuicEvent

from xpra.log import Logger

log = Logger("quic")

AsgiApplication = Callable
HttpConnection = Union[H0Connection, H3Connection]

SERVER_NAME = "aioquic/" + aioquic.__version__


class HttpRequestHandler:
    def __init__(
        self,
        *,
        authority: bytes,
        connection: HttpConnection,
        protocol: QuicConnectionProtocol,
        scope: Dict,
        stream_ended: bool,
        stream_id: int,
        transmit: Callable[[], None],
    ) -> None:
        self.authority = authority
        self.connection = connection
        self.protocol = protocol
        self.queue: asyncio.Queue[Dict] = asyncio.Queue()
        self.scope = scope
        self.stream_id = stream_id
        self.transmit = transmit

        if stream_ended:
            self.queue.put_nowait({"type": "http.request"})

    def http_event_received(self, event: H3Event) -> None:
        log(f"http_event_received({event!r})")
        if isinstance(event, DataReceived):
            self.queue.put_nowait(
                {
                    "type": "http.request",
                    "body": event.data,
                    "more_body": not event.stream_ended,
                }
            )
        elif isinstance(event, HeadersReceived) and event.stream_ended:
            self.queue.put_nowait(
                {"type": "http.request", "body": b"", "more_body": False}
            )

    async def run_asgi(self, app: AsgiApplication) -> None:
        log(f"http:run_asgi({app!r})")
        await app(self.scope, self.receive, self.send)

    async def receive(self) -> Dict:
        log("http:receive()")
        return await self.queue.get()

    async def send(self, message: Dict) -> None:
        log(f"http:send({message})")
        if message["type"] == "http.response.start":
            self.connection.send_headers(
                stream_id=self.stream_id,
                headers=[
                    (b":status", str(message["status"]).encode()),
                    (b"server", SERVER_NAME.encode()),
                    (b"date", formatdate(time.time(), usegmt=True).encode()),
                ]
                + list(message["headers"] or []),
            )
        elif message["type"] == "http.response.body":
            self.connection.send_data(
                stream_id=self.stream_id,
                data=message.get("body", b""),
                end_stream=not message.get("more_body", False),
            )
        elif message["type"] == "http.response.push" and isinstance(
            self.connection, H3Connection
        ):
            request_headers = [
                (b":method", b"GET"),
                (b":scheme", b"https"),
                (b":authority", self.authority),
                (b":path", message["path"].encode()),
            ] + list(message["headers"])

            # send push promise
            try:
                push_stream_id = self.connection.send_push_promise(
                    stream_id=self.stream_id, headers=request_headers
                )
            except NoAvailablePushIDError:
                return

            # fake request
            cast(HttpServerProtocol, self.protocol).http_event_received(
                HeadersReceived(
                    headers=request_headers, stream_ended=True, stream_id=push_stream_id
                )
            )
        self.transmit()


class WebSocketHandler:
    def __init__(
        self,
        *,
        connection: HttpConnection,
        scope: Dict,
        stream_id: int,
        transmit: Callable[[], None],
    ) -> None:
        self.closed = False
        self.connection = connection
        self.http_event_queue: Deque[DataReceived] = deque()
        self.queue: asyncio.Queue[Dict] = asyncio.Queue()
        self.scope = scope
        self.stream_id = stream_id
        self.transmit = transmit
        self.websocket: Optional[wsproto.Connection] = None

    def http_event_received(self, event: H3Event) -> None:
        log(f"ws:http_event_received({event})")
        if isinstance(event, DataReceived) and not self.closed:
            if self.websocket is not None:
                self.websocket.receive_data(event.data)

                for ws_event in self.websocket.events():
                    self.websocket_event_received(ws_event)
            else:
                # delay event processing until we get `websocket.accept`
                # from the ASGI application
                self.http_event_queue.append(event)

    def websocket_event_received(self, event: wsproto.events.Event) -> None:
        log(f"ws:websocket_event_received({event})")
        if isinstance(event, wsproto.events.TextMessage):
            self.queue.put_nowait({"type": "websocket.receive", "text": event.data})
        elif isinstance(event, wsproto.events.Message):
            self.queue.put_nowait({"type": "websocket.receive", "bytes": event.data})
        elif isinstance(event, wsproto.events.CloseConnection):
            self.queue.put_nowait({"type": "websocket.disconnect", "code": event.code})

    async def run_asgi(self, app: AsgiApplication) -> None:
        log(f"ws:run_asgi({app!r})")
        self.queue.put_nowait({"type": "websocket.connect"})

        try:
            await app(self.scope, self.receive, self.send)
        finally:
            if not self.closed:
                await self.send({"type": "websocket.close", "code": 1000})

    async def receive(self) -> Dict:
        log("ws:receive()")
        return await self.queue.get()

    async def send(self, message: Dict) -> None:
        log(f"ws:send({message})")
        data = b""
        end_stream = False
        if message["type"] == "websocket.accept":
            subprotocol = message.get("subprotocol")

            self.websocket = wsproto.Connection(wsproto.ConnectionType.SERVER)

            headers = [
                (b":status", b"200"),
                (b"server", SERVER_NAME.encode()),
                (b"date", formatdate(time.time(), usegmt=True).encode()),
            ]
            if subprotocol is not None:
                headers.append((b"sec-websocket-protocol", subprotocol.encode()))
            self.connection.send_headers(stream_id=self.stream_id, headers=headers)

            # consume backlog
            while self.http_event_queue:
                self.http_event_received(self.http_event_queue.popleft())

        elif message["type"] == "websocket.close":
            if self.websocket is not None:
                data = self.websocket.send(
                    wsproto.events.CloseConnection(code=message["code"])
                )
            else:
                self.connection.send_headers(
                    stream_id=self.stream_id, headers=[(b":status", b"403")]
                )
            end_stream = True
        elif message["type"] == "websocket.send":
            if message.get("text") is not None:
                data = self.websocket.send(
                    wsproto.events.TextMessage(data=message["text"])
                )
            elif message.get("bytes") is not None:
                data = self.websocket.send(
                    wsproto.events.Message(data=message["bytes"])
                )

        if data:
            self.connection.send_data(
                stream_id=self.stream_id, data=data, end_stream=end_stream
            )
        if end_stream:
            self.closed = True
        self.transmit()


class WebTransportHandler:
    def __init__(
        self,
        *,
        connection: HttpConnection,
        scope: Dict,
        stream_id: int,
        transmit: Callable[[], None],
    ) -> None:
        self.accepted = False
        self.closed = False
        self.connection = connection
        self.http_event_queue: Deque[DataReceived] = deque()
        self.queue: asyncio.Queue[Dict] = asyncio.Queue()
        self.scope = scope
        self.stream_id = stream_id
        self.transmit = transmit

    def http_event_received(self, event: H3Event) -> None:
        log(f"wt:http_event_received({event})")
        if not self.closed:
            if self.accepted:
                if isinstance(event, DatagramReceived):
                    self.queue.put_nowait(
                        {
                            "data": event.data,
                            "type": "webtransport.datagram.receive",
                        }
                    )
                elif isinstance(event, WebTransportStreamDataReceived):
                    self.queue.put_nowait(
                        {
                            "data": event.data,
                            "stream": event.stream_id,
                            "type": "webtransport.stream.receive",
                        }
                    )
            else:
                # delay event processing until we get `webtransport.accept`
                # from the ASGI application
                self.http_event_queue.append(event)

    async def run_asgi(self, app: AsgiApplication) -> None:
        log(f"wt:run_asgi({app})")
        self.queue.put_nowait({"type": "webtransport.connect"})

        try:
            await app(self.scope, self.receive, self.send)
        finally:
            if not self.closed:
                await self.send({"type": "webtransport.close"})

    async def receive(self) -> Dict:
        log("wt:receive()")
        return await self.queue.get()

    async def send(self, message: Dict) -> None:
        log(f"wt:send({message})")
        data = b""
        end_stream = False

        if message["type"] == "webtransport.accept":
            self.accepted = True

            headers = [
                (b":status", b"200"),
                (b"server", SERVER_NAME.encode()),
                (b"date", formatdate(time.time(), usegmt=True).encode()),
                (b"sec-webtransport-http3-draft", b"draft02"),
            ]
            self.connection.send_headers(stream_id=self.stream_id, headers=headers)

            # consume backlog
            while self.http_event_queue:
                self.http_event_received(self.http_event_queue.popleft())
        elif message["type"] == "webtransport.close":
            if not self.accepted:
                self.connection.send_headers(
                    stream_id=self.stream_id, headers=[(b":status", b"403")]
                )
            end_stream = True
        elif message["type"] == "webtransport.datagram.send":
            self.connection.send_datagram(flow_id=self.stream_id, data=message["data"])
        elif message["type"] == "webtransport.stream.send":
            self.connection._quic.send_stream_data(
                stream_id=message["stream"], data=message["data"]
            )

        if data or end_stream:
            self.connection.send_data(
                stream_id=self.stream_id, data=data, end_stream=end_stream
            )
        if end_stream:
            self.closed = True
        self.transmit()


Handler = Union[HttpRequestHandler, WebSocketHandler, WebTransportHandler]


class HttpServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        log(f"HttpServerProtocol({args}, {kwargs})")
        super().__init__(*args, **kwargs)
        self._handlers: Dict[int, Handler] = {}
        self._http: Optional[HttpConnection] = None

    async def app(self, scope, receive, send):
        raise NotImplementedError()

    def http_event_received(self, event: H3Event) -> None:
        log(f"hsp:http_event_received({event})")
        if isinstance(event, HeadersReceived) and event.stream_id not in self._handlers:
            authority = None
            headers = []
            http_version = "0.9" if isinstance(self._http, H0Connection) else "3"
            raw_path = b""
            method = ""
            protocol = None
            for header, value in event.headers:
                if header == b":authority":
                    authority = value
                    headers.append((b"host", value))
                elif header == b":method":
                    method = value.decode()
                elif header == b":path":
                    raw_path = value
                elif header == b":protocol":
                    protocol = value.decode()
                elif header and not header.startswith(b":"):
                    headers.append((header, value))

            if b"?" in raw_path:
                path_bytes, query_string = raw_path.split(b"?", maxsplit=1)
            else:
                path_bytes, query_string = raw_path, b""
            path = path_bytes.decode()
            log.info("HTTP request %s %s", method, path)

            # FIXME: add a public API to retrieve peer address
            client_addr = self._http._quic._network_paths[0].addr
            client = (client_addr[0], client_addr[1])

            handler: Handler
            scope: Dict
            scope = {
                "client": client,
                "headers": headers,
                "http_version": http_version,
                "method": method,
                "path": path,
                "query_string": query_string,
                "raw_path": raw_path,
                "root_path": "",
            }
            if method == "CONNECT" and protocol == "websocket":
                subprotocols: List[str] = []
                for header, value in event.headers:
                    if header == b"sec-websocket-protocol":
                        subprotocols = [x.strip() for x in value.decode().split(",")]
                scope.update({
                    "subprotocols"  : subprotocols,
                    "type"          : "websocket",
                    "scheme"        : "wss",
                    })
                handler = WebSocketHandler(
                    connection=self._http,
                    scope=scope,
                    stream_id=event.stream_id,
                    transmit=self.transmit,
                )
            elif method == "CONNECT" and protocol == "webtransport":
                scope = {
                    "scheme"        : "https",
                    "type"          : "webtransport",
                }
                handler = WebTransportHandler(
                    connection=self._http,
                    scope=scope,
                    stream_id=event.stream_id,
                    transmit=self.transmit,
                )
            else:
                extensions: Dict[str, Dict] = {}
                if isinstance(self._http, H3Connection):
                    extensions["http.response.push"] = {}
                scope.update({
                    "scheme": "https",
                    "type": "http",
                })
                handler = HttpRequestHandler(
                    authority=authority,
                    connection=self._http,
                    protocol=self,
                    scope=scope,
                    stream_ended=event.stream_ended,
                    stream_id=event.stream_id,
                    transmit=self.transmit,
                )
            self._handlers[event.stream_id] = handler
            asyncio.ensure_future(handler.run_asgi(self.app))
        elif (
            isinstance(event, (DataReceived, HeadersReceived))
            and event.stream_id in self._handlers
        ):
            handler = self._handlers[event.stream_id]
            handler.http_event_received(event)
        elif isinstance(event, DatagramReceived):
            handler = self._handlers[event.flow_id]
            handler.http_event_received(event)
        elif isinstance(event, WebTransportStreamDataReceived):
            handler = self._handlers[event.session_id]
            handler.http_event_received(event)

    def quic_event_received(self, event: QuicEvent) -> None:
        log(f"hsp:quic_event_received({event})")
        if isinstance(event, ProtocolNegotiated):
            if event.alpn_protocol in H3_ALPN:
                self._http = H3Connection(self._quic, enable_webtransport=True)
            elif event.alpn_protocol in H0_ALPN:
                self._http = H0Connection(self._quic)
        elif isinstance(event, DatagramFrameReceived):
            if event.data == b"quack":
                self._quic.send_datagram_frame(b"quack-ack")

        #  pass event to the HTTP layer
        if self._http is not None:
            for http_event in self._http.handle_event(event):
                self.http_event_received(http_event)
