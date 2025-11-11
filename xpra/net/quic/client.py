# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import os
import socket
import ipaddress
from queue import SimpleQueue
from typing import Union, cast
from collections.abc import Callable

from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent
from aioquic.quic.packet import QuicErrorCode
from aioquic.h3.connection import H3_ALPN
from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import (
    DataReceived,
    H3Event,
    HeadersReceived,
    PushPromiseReceived,
)
from aioquic.quic.connection import QuicConnection
from aioquic.asyncio.protocol import QuicConnectionProtocol

from xpra.os_util import POSIX
from xpra.scripts.config import InitExit
from xpra.exit_codes import ExitCode
from xpra.net.bytestreams import pretty_socket
from xpra.net.socket_util import create_udp_socket
from xpra.net.ssl.parsing import parse_ssl_verify_mode
from xpra.net.asyncio.thread import get_threaded_loop
from xpra.net.quic.connection import XpraQuicConnection, aioquic_version_info
from xpra.net.quic.common import USER_AGENT, MAX_DATAGRAM_FRAME_SIZE, binary_headers
from xpra.util.str_fn import csv, Ellipsizer
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]

IPV6 = socket.has_ipv6 and envbool("XPRA_IPV6", True)
PREFER_IPV6 = IPV6 and envbool("XPRA_PREFER_IPV6", POSIX)
HOSTS_PREFER_IPV4 = os.environ.get("XPRA_HOSTS_PREFER_IPV4", "localhost,127.0.0.1").split(",")
FAST_OPEN = envbool("XPRA_QUIC_FAST_OPEN", aioquic_version_info >= (1, 2))

WS_HEADERS: dict[str, str] = {
    ":method": "CONNECT",
    ":scheme": "https",
    ":protocol": "websocket",
    "sec-websocket-version": 13,
    "sec-websocket-protocol": "xpra",
    "user-agent": USER_AGENT,
}


class ClientWebSocketConnection(XpraQuicConnection):

    def __init__(self, connection: HttpConnection, stream_id: int, transmit: Callable[[], None],
                 host: str, port: int, info=None, options=None):
        super().__init__(connection, stream_id, transmit, host, port, "wss", info, options)
        self.write_buffer = SimpleQueue()

    def flush_writes(self) -> None:
        # flush the buffered writes:
        try:
            while self.write_buffer.qsize():
                self.stream_write(*self.write_buffer.get())
        finally:
            self.write_buffer = None

    def write(self, buf, packet_type: str = "") -> int:
        log(f"write(%s, %s) {len(buf)} bytes", Ellipsizer(buf), packet_type)
        if self.write_buffer is not None:
            # buffer it until we are connected and call flush_writes()
            self.write_buffer.put((buf, packet_type))
            return len(buf)
        return super().write(buf, packet_type)

    def http_event_received(self, event: H3Event) -> None:
        log("http_event_received(%s)", Ellipsizer(event))
        if isinstance(event, HeadersReceived):
            for header, value in event.headers:
                if header == b"sec-websocket-protocol":
                    subprotocols = value.decode().split(",")
                    if "xpra" not in subprotocols:
                        message = f"unsupported websocket subprotocols {subprotocols}"
                        log.warn(f"Warning: {message}")
                        if not self.accepted:
                            self.send_headers(self.stream_id, headers={":status": 501})
                            self.transmit()
                        self.close(QuicErrorCode.APPLICATION_ERROR, message)
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http: HttpConnection | None = None
        self._push_types: dict[str, int] = {}
        self._websockets: dict[int, ClientWebSocketConnection] = {}
        if self._quic.configuration.alpn_protocols[0].startswith("hq-"):
            self._http = H0Connection(self._quic)
        else:
            self._http = H3Connection(self._quic)

    def open(self, host: str, port: int, path: str) -> ClientWebSocketConnection:
        log(f"open({host}, {port}, {path})")
        stream_id = self._quic.get_next_available_stream_id()
        websocket = ClientWebSocketConnection(self._http, stream_id, self.transmit,
                                              host, port)
        self._websockets[stream_id] = websocket
        headers = {
            ":authority": host,
            ":path": path,
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
        websocket: ClientWebSocketConnection | None = self._websockets.get(stream_id)
        if not websocket:
            # perhaps this is a new substream?
            sub = -1
            hdict = {}
            if isinstance(event, HeadersReceived):
                hdict = {k.decode(): v.decode() for k, v in event.headers}
                sub = int(hdict.get("substream", -1))
            if sub < 0:
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


def create_local_socket(family=socket.AF_INET) -> tuple[socket.socket, tuple[str, int]]:
    if family == socket.AF_INET6:
        local_host = "::"
    else:
        local_host = "0.0.0.0"
    local_port = 0
    sock = create_udp_socket(local_host, local_port, family)
    addr = (local_host, local_port)
    log(f"create_udp_socket({pretty_socket(addr)}, {family})={sock}")
    return sock, addr


async def get_address_options(host: str, port: int) -> tuple:
    if IPV6:
        family = socket.AF_UNSPEC
        family_options = (socket.AF_INET, socket.AF_INET6)
    else:
        family = socket.AF_INET
        family_options = (socket.AF_INET,)
    try:
        tl = get_threaded_loop()
        infos = await tl.loop.getaddrinfo(host, port, family=family, type=socket.SOCK_DGRAM)
        log(f"getaddrinfo({host}, {port}, {family}, SOCK_DGRAM)={infos}")
    except Exception as e:
        log(f"getaddrinfo({host}, {port}, {family}, SOCK_DGRAM)", exc_info=True)
        raise RuntimeError(f"cannot get address information for {pretty_socket((host, port))}: {e}") from None
    if IPV6:
        # we have to filter the results ourselves:
        infos = list(addr_info for addr_info in infos if addr_info[0] in family_options)
    has_ipv6 = any(addr_info[0] == socket.AF_INET6 for addr_info in infos)
    prefer_ipv4 = any(re.match(host_pattern, host) for host_pattern in HOSTS_PREFER_IPV4)
    if prefer_ipv4 and has_ipv6:
        # IPv6 is a waste of time on loopback,
        # and it can cause problems on some addresses,
        # so make sure it comes last in the list:
        infos.sort(key=lambda info: int(info[0] == socket.AF_INET6))
    elif PREFER_IPV6 and not has_ipv6:
        # no ipv6 returned, cook one up:
        ipv4_infos = tuple(addr_info for addr_info in infos if addr_info[0] == socket.AF_INET)
        # ie:( (<AddressFamily.AF_INET: 2>, <SocketKind.SOCK_DGRAM: 2>, 17, '', ('192.168.0.114', 10000)), )
        if ipv4_infos:
            ipv4 = ipv4_infos[0]
            addr = ipv4[4]  # ie: ('192.168.0.114', 10000)
            if len(addr) == 2:
                addr = ("::ffff:" + addr[0], addr[1], 0, 0)
                infos.insert(0, (socket.AF_INET6, socket.SOCK_DGRAM, ipv4[2], ipv4[3], addr))
                log(f"added IPv6 option: {infos[0]}")
    # ensure only the family_options we want are included,
    # (only really needed for AF_UNSPEC)
    return tuple(infos)


def quic_connect(host: str, port: int, path: str, fast_open: bool,
                 ssl_cert: str, ssl_key: str, ssl_key_password: str,
                 ssl_ca_certs, ssl_server_verify_mode: str, ssl_server_name: str):
    configuration = QuicConfiguration(
        alpn_protocols=H3_ALPN,
        is_client=True,
        max_datagram_frame_size=MAX_DATAGRAM_FRAME_SIZE,
    )
    configuration.verify_mode = parse_ssl_verify_mode(ssl_server_verify_mode)
    if ssl_ca_certs:
        configuration.load_verify_locations(ssl_ca_certs)
    if ssl_cert:
        from pathlib import Path
        cert_path = Path(ssl_cert)
        key_path = Path(ssl_key) if ssl_key else None
        configuration.load_cert_chain(cert_path, key_path, ssl_key_password or None)
    if ssl_server_name:
        configuration.server_name = ssl_server_name
    else:
        # if host is not an IP address, use it for SNI:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            configuration.server_name = host

    # configuration.max_data = args.max_data
    # configuration.max_stream_data = args.max_stream_data
    # configuration.quic_logger = QuicFileLogger(args.quic_log)
    # configuration.secrets_log_file = open(args.secrets_log, "a")

    def create_protocol() -> WebSocketClient:
        connection = QuicConnection(configuration=configuration)
        return WebSocketClient(connection)

    tl = get_threaded_loop()
    log(f"getting the list of address options for {host!r}:{port}")
    addresses = tl.sync(get_address_options, host, port)
    log(f"quic_connect will try {addresses=}")

    async def connect(addr_info):
        # ie:(AF_INET, SOCK_DGRAM, 0, '', ('192.168.0.10', 10000)
        log(f"connect({addr_info})")
        af = addr_info[0]
        sock, local_addr = create_local_socket(af)
        transport, protocol = await tl.loop.create_datagram_endpoint(create_protocol, sock=sock)
        log(f"{transport=}, {protocol=}")
        protocol = cast(QuicConnectionProtocol, protocol)
        addr = addr_info[4]  # ie: ('192.168.0.10', 10000)
        log(f"connecting from {pretty_socket(local_addr)} to {pretty_socket(addr)} with {fast_open=}")
        if fast_open:
            protocol.connect(addr, transmit=False)
        else:
            protocol.connect(addr)
        log("awaiting connected state")
        try:
            if not fast_open:
                await protocol.wait_connected()
            else:
                from xpra.scripts.main import CONNECT_TIMEOUT
                tl.call_later(CONNECT_TIMEOUT, verify_connected, protocol)
            log(f"{protocol}.open({host!r}, {port}, {path!r})")
            conn = protocol.open(host, port, path)
            log(f"websocket connection {conn}")
            return conn
        except Exception as e:
            log("connect()", exc_info=True)
            # try to get a more meaningful exception message:
            einfo = str(e)
            if not einfo:
                quic_conn = getattr(protocol, "_quic", None)
                if quic_conn:
                    close_event = getattr(quic_conn, "_close_event", None)
                    log(f"{close_event=}, {dir(close_event)}")
                    if close_event:
                        err = close_event.error_code
                        msg = close_event.reason_phrase
                        if err & QuicErrorCode.CRYPTO_ERROR:
                            raise InitExit(ExitCode.CONNECTION_FAILED, msg)
                        # if (err & 0xFF)==QuicErrorCode.CONNECTION_REFUSED:
                        #    raise InitExit(ExitCode.CONNECTION_FAILED, msg)
                        raise RuntimeError(close_event.reason_phrase) from None
            raise RuntimeError(str(e)) from None

    # protocol.close()
    # await protocol.wait_closed()
    # transport.close()
    if len(addresses) == 1:
        return tl.sync(connect, addresses[0])

    errors = []
    for address in addresses:
        try:
            return tl.sync(connect, address)
        except Exception as ce:
            log("failed to connect:", exc_info=True)
            estr = str(ce) or type(ce)
            if estr not in errors:
                errors.append(estr)
    raise InitExit(ExitCode.CONNECTION_FAILED, "failed to connect: " + csv(errors))


def verify_connected(protocol) -> None:
    # this is only useful for debugging,
    # as we have no way to send a message to the main thread,
    # I guess it may still show up in some debug log?
    log("verify_connect(%s) connected=%s", protocol, protocol._connected)
