# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import ipaddress
from queue import Queue
from typing import Dict, Callable, Optional, Union, cast

from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent
from aioquic.h3.connection import H3_ALPN
from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import (
    DataReceived,
    H3Event,
    HeadersReceived,
    PushPromiseReceived,
)
from aioquic.tls import SessionTicket
from aioquic.quic.connection import QuicConnection
from aioquic.asyncio.protocol import QuicConnectionProtocol

from xpra.os_util import POSIX
from xpra.net.bytestreams import pretty_socket
from xpra.net.socket_util import get_ssl_verify_mode, create_udp_socket
from xpra.net.quic.connection import XpraQuicConnection
from xpra.net.quic.asyncio_thread import get_threaded_loop
from xpra.net.quic.common import USER_AGENT, MAX_DATAGRAM_FRAME_SIZE, binary_headers
from xpra.util import ellipsizer, envbool, csv
from xpra.log import Logger
log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]

IPV6 = socket.has_ipv6 and envbool("XPRA_IPV6", True)
PREFER_IPV6 = IPV6 and envbool("XPRA_PREFER_IPV6", POSIX)


def save_session_ticket(ticket: SessionTicket) -> None:
    pass

WS_HEADERS = {
        ":method"   : "CONNECT",
        ":scheme"   : "https",
        ":protocol" : "websocket",
        "sec-websocket-version" : 13,
        "sec-websocket-protocol" : "xpra",
        "user-agent" : USER_AGENT,
        }


class ClientWebSocketConnection(XpraQuicConnection):

    def __init__(self, connection : HttpConnection, stream_id: int, transmit: Callable[[], None],
                 host : str, port : int, info=None, options=None) -> None:
        super().__init__(connection, stream_id, transmit, host, port, info, options)
        self.write_buffer = Queue()

    def flush_writes(self):
        #flush the buffered writes:
        try:
            while self.write_buffer.qsize():
                self.stream_write(*self.write_buffer.get())
        finally:
            self.write_buffer = None

    def write(self, buf, packet_type=None):
        log(f"write(%s, %s) {len(buf)} bytes", ellipsizer(buf), packet_type)
        if self.write_buffer is not None:
            #buffer it until we are connected and call flush_writes()
            self.write_buffer.put((buf, packet_type))
            return len(buf)
        return super().write(buf, packet_type)

    def http_event_received(self, event: H3Event) -> None:
        log("http_event_received(%s)", ellipsizer(event))
        if isinstance(event, HeadersReceived):
            for header, value in event.headers:
                if header == b"sec-websocket-protocol":
                    subprotocols = value.decode().split(",")
                    if "xpra" not in subprotocols:
                        log.warn(f"Warning: unsupported websocket subprotocols {subprotocols}")
                        self.close()
                        return
                    self.accepted = True
                    self.flush_writes()
            return
        if isinstance(event, PushPromiseReceived):
            log(f"PushPromiseReceived: {event}")
            log(f"PushPromiseReceived headers: {event.headers}")
            return
        super().http_event_received(event)


class WebSocketClient(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._http: Optional[HttpConnection] = None
        self._push_types: Dict[str, int] = {}
        self._websockets: Dict[int, ClientWebSocketConnection] = {}
        if self._quic.configuration.alpn_protocols[0].startswith("hq-"):
            self._http = H0Connection(self._quic)
        else:
            self._http = H3Connection(self._quic)

    def open(self, host : str, port : int, path : str) -> ClientWebSocketConnection:
        log(f"open({host}, {port}, {path})")
        stream_id = self._quic.get_next_available_stream_id()
        websocket = ClientWebSocketConnection(self._http, stream_id, self.transmit,
                                              host, port)
        self._websockets[stream_id] = websocket
        headers = {
            ":authority" : host,
            ":path" : path,
            }
        headers.update(WS_HEADERS)
        log("open: sending http headers for websocket upgrade")
        self._http.send_headers(stream_id=stream_id, headers=binary_headers(headers))
        self.transmit()
        return websocket

    def quic_event_received(self, event: QuicEvent) -> None:
        for http_event in self._http.handle_event(event):
            self.http_event_received(http_event)

    def http_event_received(self, event: H3Event) -> None:
        if not isinstance(event, (HeadersReceived, DataReceived, PushPromiseReceived)):
            log.warn(f"Warning: unexpected http event type: {event}")
            return
        stream_id = event.stream_id
        websocket : Optional[ClientWebSocketConnection] = self._websockets.get(stream_id)
        if not websocket:
            #perhaps this is a new substream?
            sub = -1
            hdict = {}
            if isinstance(event, HeadersReceived):
                hdict = dict((k.decode(),v.decode()) for k,v in event.headers)
                sub = int(hdict.get("substream", -1))
            if sub<0:
                log.warn(f"Warning: unexpected websocket stream id: {stream_id} in {event}")
                return
            websocket = self._websockets.get(sub)
            if not websocket:
                log.warn(f"Warning: stream {sub} not found in {self._websockets}")
                return
            subtype = hdict.get("stream-type")
            log.info(f"new quic substream {stream_id} for {subtype} packets")
            self._websockets[stream_id] = websocket
        websocket.http_event_received(event)


def quic_connect(host : str, port : int, path : str,
                 ssl_cert : str, ssl_key : str, ssl_key_password : str,
                 ssl_ca_certs, ssl_server_verify_mode : str, ssl_server_name : str):
    configuration = QuicConfiguration(
        alpn_protocols=H3_ALPN,
        is_client=True,
        max_datagram_frame_size=MAX_DATAGRAM_FRAME_SIZE,
        )
    configuration.verify_mode = get_ssl_verify_mode(ssl_server_verify_mode)
    if ssl_ca_certs:
        configuration.load_verify_locations(ssl_ca_certs)
    if ssl_cert:
        configuration.load_cert_chain(ssl_cert, ssl_key or None, ssl_key_password or None)
    if ssl_server_name:
        configuration.server_name = ssl_server_name
    else:
        # if host is not an IP address, use it for SNI:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            configuration.server_name = host
    #configuration.max_data = args.max_data
    #configuration.max_stream_data = args.max_stream_data
    #configuration.quic_logger = QuicFileLogger(args.quic_log)
    #configuration.secrets_log_file = open(args.secrets_log, "a")
    connection = QuicConnection(configuration=configuration, session_ticket_handler=save_session_ticket)

    def create_local_socket(family=socket.AF_INET):
        if family==socket.AF_INET6:
            local_host = "::"
        else:
            local_host = "0.0.0.0"
        local_port = 0
        sock = create_udp_socket(local_host, local_port, family)
        addr = (local_host, local_port)
        log(f"create_udp_socket({pretty_socket(addr)}, {family})={sock}")
        return sock, addr
    tl = get_threaded_loop()

    def create_protocol():
        return WebSocketClient(connection)

    async def connect():
        log("quic_connect: connect()")
        if IPV6:
            family = socket.AF_UNSPEC
            family_options = (socket.AF_INET, socket.AF_INET6)
        else:
            family = socket.AF_INET
            family_options = (socket.AF_INET, )
        try:
            infos = await tl.loop.getaddrinfo(host, port, family=family, type=socket.SOCK_DGRAM)
            log(f"getaddrinfo({host}, {port}, {family}, SOCK_DGRAM)={infos}")
        except Exception as e:
            log(f"getaddrinfo({host}, {port}, {family}, SOCK_DGRAM)={infos}", exc_info=True)
            raise RuntimeError(f"cannot get address information for {pretty_socket((host, port))}: {e}") from None
        if PREFER_IPV6 and not any(addr_info[0]==socket.AF_INET6 for addr_info in infos):
            #no ipv6 returned, cook one up:
            ipv4_infos = tuple(addr_info for addr_info in infos if addr_info[0]==socket.AF_INET)
            #ie:( (<AddressFamily.AF_INET: 2>, <SocketKind.SOCK_DGRAM: 2>, 17, '', ('192.168.0.114', 10000)), )
            if ipv4_infos:
                ipv4 = ipv4_infos[0]
                addr = ipv4[4]          #ie: ('192.168.0.114', 10000)
                if len(addr)==2:
                    addr = ("::ffff:" + addr[0], addr[1], 0, 0)
                    infos.insert(0, (socket.AF_INET6, socket.SOCK_DGRAM, ipv4[2], ipv4[3], addr))
                    log(f"added IPv6 option: {infos[0]}")
        errors = []
        for addr_info in infos:
            #ie:(AF_INET, SOCK_DGRAM, 0, '', ('192.168.0.10', 10000)
            log(f"trying {addr_info}")
            af = addr_info[0]
            if af not in family_options:
                continue
            sock, local_addr = create_local_socket(af)
            transport, protocol = await tl.loop.create_datagram_endpoint(create_protocol, sock=sock)
            log(f"transport={transport}, protocol={protocol}")
            protocol = cast(QuicConnectionProtocol, protocol)
            addr = addr_info[4]     #ie: ('192.168.0.10', 10000)
            log(f"connecting from {pretty_socket(local_addr)} to {pretty_socket(addr)}")
            protocol.connect(addr)
            try:
                await protocol.wait_connected()
                conn = protocol.open(host, port, path)
                log(f"websocket connection {conn}")
                return conn
            except Exception as e:
                log("connect()", exc_info=True)
                #try to get a more meaningful exception message:
                einfo = str(e)
                if not einfo:
                    quic_conn = getattr(protocol, "_quic", None)
                    if quic_conn:
                        close_event = getattr(quic_conn, "_close_event", None)
                        if close_event:
                            errors.append(close_event.reason_phrase)
                            continue
                errors.append(str(e))
        raise RuntimeError(f"failed to connect: {csv(errors)}")
    #protocol.close()
    #await protocol.wait_closed()
    #transport.close()
    conn = tl.sync(connect)
    log(f"quic_connect() connect()={conn}")
    return conn
