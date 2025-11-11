# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Union

import asyncio
from aioquic.asyncio import QuicConnectionProtocol
from aioquic.asyncio.server import QuicServer
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.logger import QuicLogger
from aioquic.h0.connection import H0_ALPN, H0Connection
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import (
    DatagramReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from aioquic.quic.events import DatagramFrameReceived, ProtocolNegotiated, QuicEvent

from xpra.net.quic.common import MAX_DATAGRAM_FRAME_SIZE
from xpra.net.quic.http import HttpRequestHandler
from xpra.net.quic.websocket import ServerWebSocketConnection
from xpra.net.quic.webtransport import ServerWebTransportConnection
from xpra.net.quic.session_ticket_store import SessionTicketStore
from xpra.net.asyncio.thread import get_threaded_loop
from xpra.net.websockets.protocol import WebSocketProtocol
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.scripts.config import InitExit
from xpra.exit_codes import ExitCode
from xpra.util.str_fn import Ellipsizer
from xpra.log import Logger

log = Logger("quic")

quic_logger = QuicLogger()

HttpConnection = Union[H0Connection, H3Connection]
Handler = Union[HttpRequestHandler, ServerWebSocketConnection, ServerWebTransportConnection]


class HttpServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        self._xpra_server = kwargs.pop("xpra_server", None)
        log(f"HttpServerProtocol({args}, {kwargs}) xpra-server={self._xpra_server}")
        super().__init__(*args, **kwargs)
        self._handlers: dict[int, Handler] = {}
        self._http: HttpConnection | None = None

    def quic_event_received(self, event: QuicEvent) -> None:
        log("hsp:quic_event_received(%s)", Ellipsizer(event))
        if isinstance(event, ProtocolNegotiated):
            if event.alpn_protocol in H3_ALPN:
                self._http = H3Connection(self._quic, enable_webtransport=True)
            elif event.alpn_protocol in H0_ALPN:
                self._http = H0Connection(self._quic)
        elif isinstance(event, DatagramFrameReceived) and event.data == b"quack":
            self._quic.send_datagram_frame(b"quack-ack")
        #  pass event to the HTTP layer
        log(f"hsp:quic_event_received(..) http={self._http}")
        if self._http is not None:
            for http_event in self._http.handle_event(event):
                self.http_event_received(http_event)

    def http_event_received(self, event: H3Event) -> None:
        hid = event.flow_id if isinstance(event, DatagramReceived) else event.stream_id
        handler = self._handlers.get(hid)
        log(f"hsp:http_event_received(%s) handler {hid}: {handler}", Ellipsizer(event))
        if isinstance(event, HeadersReceived) and not handler:
            handler = self.new_http_handler(event)
            self._handlers[event.stream_id] = handler
        elif isinstance(event, DatagramReceived):
            handler = self._handlers[event.flow_id]
        elif isinstance(event, WebTransportStreamDataReceived):
            handler = self._handlers[event.session_id]
        log(f"handler for {event} = {handler}")
        if handler:
            handler.http_event_received(event)

    def new_http_handler(self, event) -> Handler:
        authority = None
        headers = []
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

        log(f"new_http_handler({event}) {path=}, {query_string=}")
        log(f" {protocol=}, {method=}, {authority=}, {headers=}")

        # this was copied from the aioquic example,
        # let's hope this does not break!
        client_addr = self._http._quic._network_paths[0].addr
        client = (client_addr[0], client_addr[1])

        einfo = {}
        for k in ("peername", "sockname", "compression", "cipher", "peercert", "sslcontext"):
            v = self._transport.get_extra_info(k)
            if v:
                einfo[k] = v

        scope = {
            "client": client,
            "headers": headers,
            "http_version": "0.9" if isinstance(self._http, H0Connection) else "3",
            "method": method,
            "path": path,
            "query_string": query_string,
            "raw_path": raw_path,
            "transport-info": einfo,
        }
        if method == "CONNECT" and protocol == "websocket":
            subprotocols: list[str] = []
            for header, value in event.headers:
                if header == b"sec-websocket-protocol":
                    subprotocols = [x.strip() for x in value.decode().split(",")]
            scope |= {
                "subprotocols": subprotocols,
                "type": "websocket",
                "scheme": "wss",
            }
            wsc = ServerWebSocketConnection(connection=self._http, scope=scope,
                                            stream_id=event.stream_id,
                                            transmit=self.transmit)
            socket_options = {}
            self._xpra_server.make_protocol("quic", wsc, socket_options, protocol_class=WebSocketProtocol)
            return wsc

        if method == "CONNECT" and protocol == "webtransport":
            scope |= {
                "scheme": "https",
                "type": "webtransport",
            }
            log.info("WebTransport request at %s", path)
            wtc = ServerWebTransportConnection(connection=self._http, scope=scope,
                                               stream_id=event.stream_id,
                                               transmit=self.transmit)
            socket_options = {}
            self._xpra_server.make_protocol("webtransport", wtc, socket_options, protocol_class=SocketProtocol)
            return wtc
        # extensions: dict[str, dict] = {}
        # if isinstance(self._http, H3Connection):
        #    extensions["http.response.push"] = {}
        scope |= {
            "scheme": "https",
            "type": "http",
        }
        return HttpRequestHandler(xpra_server=self._xpra_server,
                                  authority=authority, connection=self._http,
                                  protocol=self,
                                  scope=scope,
                                  stream_id=event.stream_id,
                                  transmit=self.transmit)


async def do_listen(sock, xpra_server, cert: str, key: str | None, retry: bool):
    log(f"do_listen({sock}, {xpra_server}, {cert}, {key}, {retry})")

    def create_protocol(*args, **kwargs):
        return HttpServerProtocol(*args, xpra_server=xpra_server, **kwargs)

    configuration = QuicConfiguration(
        alpn_protocols=H3_ALPN + H0_ALPN + ["siduck"],
        is_client=False,
        max_datagram_frame_size=MAX_DATAGRAM_FRAME_SIZE,
        quic_logger=quic_logger,
    )
    try:
        configuration.load_cert_chain(cert, key)
    except FileNotFoundError as e:
        log(f"load_cert_chain({cert!r}, {key!r}")
        log.error("Error: cannot create QUIC protocol")
        log.estr(e)
        return None
    try:
        log(f"quic {configuration=}")
        session_ticket_store = SessionTicketStore()

        def create_server() -> QuicServer:
            return QuicServer(
                configuration=configuration,
                create_protocol=create_protocol,
                session_ticket_fetcher=session_ticket_store.pop,
                session_ticket_handler=session_ticket_store.add,
                retry=retry,
            )

        loop = asyncio.get_event_loop()
        r = await loop.create_datagram_endpoint(create_server, sock=sock)
        log(f"create_datagram_endpoint({create_server}, {sock})={r}")
        return r
    except Exception:
        log.error(f"Error: listening on {sock}", exc_info=True)
        raise


def listen_quic(sock, xpra_server, socket_options: dict) -> None:
    from xpra.net.ssl.file import find_ssl_cert
    from xpra.net.ssl.common import SSL_CERT_FILENAME
    from xpra.net.ssl.common import KEY_FILENAME
    log(f"listen_quic({sock}, {xpra_server}, {socket_options})")
    ssl_socket_options = xpra_server.get_ssl_socket_options(socket_options)
    cert = ssl_socket_options.get("cert", "") or find_ssl_cert(SSL_CERT_FILENAME)
    key = ssl_socket_options.get("key", "") or find_ssl_cert(KEY_FILENAME)
    if not cert:
        raise InitExit(ExitCode.SSL_FAILURE, "missing ssl certificate")
    if not key:
        raise InitExit(ExitCode.SSL_FAILURE, "missing ssl key")
    retry = socket_options.get("retry", False)
    t = get_threaded_loop()
    t.call(do_listen(sock, xpra_server, cert, key, retry))
