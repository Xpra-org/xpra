# This file is part of Xpra.
# Copyright (C) 2019-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import uuid
from time import monotonic
from hashlib import sha1
from base64 import b64encode
from urllib.parse import quote

from xpra.os_util import strtobytes, bytestostr
from xpra.log import Logger

log = Logger("websocket")

MAX_WRITE_TIME = 5
MAX_READ_TIME = 5
READ_CHUNK_SIZE = 4096

HEADERS_MODULES = os.environ.get("XPRA_WEBSOCKET_HEADERS_MODULES", "default").split(",")


def make_websocket_accept_hash(key):
    GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept = sha1(strtobytes(key) + GUID).digest()
    return b64encode(accept)

def get_headers(host, port):
    headers = {}
    for mod_name in HEADERS_MODULES:
        try:
            header_module = __import__(f"xpra.net.websockets.headers.{mod_name}", {}, {}, ["get_headers"])
            v = header_module.get_headers(host, port)
            log(f"{mod_name}.get_headers({host}, {port})={v}")
            headers.update(v)
        except ImportError as e:
            log("import %s", mod_name, exc_info=True)
            log.error(f"Error: websocket header module {mod_name!r} not available")
            log.error(" %s", e)
        except Exception as e:
            log("get_headers %s", mod_name, exc_info=True)
            log.error(f"Error: cannot get headers from module {mod_name!r}")
            log.estr(e)
    return headers


def client_upgrade(read, write, host, port, path=""):
    key = b64encode(uuid.uuid4().bytes)
    request = get_client_upgrade_request(host, port, path, key)
    write_request(write, request)
    headers = read_server_upgrade(read)
    verify_response_headers(headers, key)
    log("client_upgrade: done")

def get_client_upgrade_request(host, port, path, key):
    url_path = quote(path)
    request = f"GET /{url_path} HTTP/1.1"
    log(f"client websocket upgrade request: {request!r}")
    lines = [request.encode("latin1")]
    headers = get_headers(host, port)
    headers[b"Sec-WebSocket-Key"] = key
    for k,v in headers.items():
        lines.append(b"%s: %s" % (k, v))
    lines.append(b"")
    lines.append(b"")
    return b"\r\n".join(lines)

def write_request(write, http_request):
    now = monotonic()
    while http_request:
        elasped = monotonic()-now
        if elasped>=MAX_WRITE_TIME:
            raise Exception(f"http write timeout, took more {elasped:.1f} seconds")
        w = write(http_request)
        http_request = http_request[w:]

def read_server_upgrade(read):
    now = monotonic()
    response = b""
    def hasheader(k):
        return k in parse_response_header(response)
    while monotonic()-now<MAX_READ_TIME and not (hasheader("sec-websocket-protocol") or hasheader("www-authenticate")):
        response += read(READ_CHUNK_SIZE)
    return parse_response_header(response)

def parse_response_header(response):
    #parse response:
    head = response.split(b"\r\n\r\n", 1)[0]
    lines = head.split(b"\r\n")
    headers = {}
    for line in lines:
        parts = bytestostr(line).split(": ", 1)
        if len(parts)==2:
            headers[parts[0].lower()] = parts[1]
    return headers

def verify_response_headers(headers, key):
    log(f"verify_response_headers({headers!r})")
    if not headers:
        raise Exception("no http headers found in response")
    if headers.get("www-authenticate"):
        raise Exception("http connection requires authentication")
    upgrade = headers.get("upgrade")
    if not upgrade:
        raise Exception("http connection was not upgraded to websocket")
    if upgrade!="websocket":
        raise Exception(f"invalid http upgrade: {upgrade!r}")
    protocol = headers.get("sec-websocket-protocol")
    if protocol!="binary":
        raise Exception(f"invalid websocket protocol: {protocol!r}")
    accept_key = headers.get("sec-websocket-accept")
    if not accept_key:
        raise Exception("websocket accept key is missing")
    expected_key = make_websocket_accept_hash(key)
    if bytestostr(accept_key)!=bytestostr(expected_key):
        log(f"expected {expected_key!r}, received {accept_key!r}")
        raise Exception("websocket accept key is invalid")
