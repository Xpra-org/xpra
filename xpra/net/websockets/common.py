# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import uuid
from time import monotonic
from hashlib import sha1
from base64 import b64encode
from urllib.parse import quote
from typing import Any
from enum import IntEnum
from collections.abc import Callable
from importlib import import_module

from xpra.util.str_fn import strtobytes
from xpra.log import Logger

log = Logger("websocket")

MAX_WRITE_TIME = 5
MAX_READ_TIME = 5
READ_CHUNK_SIZE = 4096

HEADERS_MODULES = os.environ.get("XPRA_WEBSOCKET_HEADERS_MODULES", "default").split(",")


class OPCODE(IntEnum):
    CONTINUE = 0
    TEXT = 1
    BINARY = 2
    CLOSE = 8
    PING = 9
    PONG = 10


OPCODE_STR: dict[int, str] = {
    OPCODE.CONTINUE: "CONTINUE",
    OPCODE.TEXT: "TEXT",
    OPCODE.BINARY: "BINARY",
    OPCODE.CLOSE: "CLOSE",
    OPCODE.PING: "PING",
    OPCODE.PONG: "PONG",
}


def make_websocket_accept_hash(key: bytes) -> bytes:
    GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept = sha1(key + GUID).digest()
    return b64encode(accept)


def get_headers(host: str, port: int) -> dict[bytes, bytes]:
    headers = {}
    for mod_name in HEADERS_MODULES:
        try:
            header_module = import_module(f"xpra.net.websockets.headers.{mod_name}")
            v = header_module.get_headers(host, port)
            log(f"{mod_name}.get_headers({host}, {port})={v}")
            headers.update(v)
        except ImportError as e:
            log("import %s", mod_name, exc_info=True)
            log.error(f"Error: websocket header module {mod_name!r} not available")
            log.estr(e)
        except Exception as e:
            log("get_headers %s", mod_name, exc_info=True)
            log.error(f"Error: cannot get headers from module {mod_name!r}")
            log.estr(e)
    return headers


def client_upgrade(read: Callable, write: Callable, host: str, port: int, path="") -> None:
    key = b64encode(uuid.uuid4().bytes)
    request = get_client_upgrade_request(host, port, path, key)
    write_request(write, request)
    headers = read_server_upgrade(read)
    verify_response_headers(headers, key)
    log("client_upgrade: done")


def get_client_upgrade_request(host: str, port: int, path: str, key: bytes) -> bytes:
    url_path = quote(path)
    request = f"GET /{url_path} HTTP/1.1"
    log(f"client websocket upgrade request: {request!r}")
    lines = [request.encode("latin1")]
    headers = get_headers(host, port)
    headers[b"Sec-WebSocket-Key"] = key
    for k, v in headers.items():
        lines.append(b"%s: %s" % (k, v))
    lines.append(b"")
    lines.append(b"")
    return b"\r\n".join(lines)


def write_request(write: Callable, http_request) -> None:
    now = monotonic()
    while http_request:
        elapsed = monotonic() - now
        if elapsed >= MAX_WRITE_TIME:
            raise RuntimeError(f"http write timeout, took more {elapsed:.1f} seconds")
        w = write(http_request)
        http_request = http_request[w:]


def read_server_upgrade(read: Callable) -> dict[str, str]:
    now = monotonic()
    response = b""

    def hasheader(k) -> bool:
        return k in parse_response_header(response)

    while monotonic() - now < MAX_READ_TIME and not (
            hasheader("sec-websocket-protocol") or hasheader("www-authenticate")):
        response += read(READ_CHUNK_SIZE)
    return parse_response_header(response)


def parse_response_header(response: bytes) -> dict[str, str]:
    head = response.split(b"\r\n\r\n", 1)[0]
    lines = head.split(b"\r\n")
    headers = {}
    for line in lines:
        parts = line.decode("latin1").split(": ", 1)
        if len(parts) == 2:
            headers[parts[0].lower()] = parts[1]
    return headers


def verify_response_headers(headers: dict[str, Any], key: bytes):
    log(f"verify_response_headers({headers!r}, {key!r})")
    if not headers:
        raise ValueError("no http headers found in response")
    if headers.get("www-authenticate"):
        raise ValueError("http connection requires authentication")
    upgrade = headers.get("upgrade")
    if not upgrade:
        raise ValueError("http connection was not upgraded to websocket")
    if upgrade != "websocket":
        raise ValueError(f"invalid http upgrade: {upgrade!r}")
    protocol = headers.get("sec-websocket-protocol")
    if protocol != "binary":
        raise ValueError(f"invalid websocket protocol: {protocol!r}")
    accept_key = headers.get("sec-websocket-accept")
    if not accept_key:
        raise ValueError("websocket accept key is missing")
    expected_key = make_websocket_accept_hash(key)
    if strtobytes(accept_key) != expected_key:
        log(f"expected {expected_key!r}, received {accept_key!r}")
        raise ValueError("websocket accept key is invalid")
