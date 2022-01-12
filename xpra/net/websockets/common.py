# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import uuid
from time import monotonic
from hashlib import sha1
from base64 import b64encode

from xpra.os_util import strtobytes, bytestostr
from xpra.util import u
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
            header_module = __import__("xpra.net.websockets.headers.%s" % mod_name, {}, {}, ["get_headers"])
            v = header_module.get_headers(host, port)
            log("%s.get_headers(%s, %s)=%s", mod_name, host, port, v)
            headers.update(v)
        except ImportError as e:
            log("import %s", mod_name, exc_info=True)
            log.error("Error: websocket header module %s not available", mod_name)
            log.error(" %s", e)
        except Exception as e:
            log("get_headers %s", mod_name, exc_info=True)
            log.error("Error: cannot get headers from '%s'", mod_name)
            log.error(" %s", e)
    return headers


def client_upgrade(read, write, host, port, path=""):
    lines = [b"GET /%s HTTP/1.1" % path.encode("latin1")]
    key = b64encode(uuid.uuid4().bytes)
    headers = get_headers(host, port)
    headers[b"Sec-WebSocket-Key"] = key
    for k,v in headers.items():
        lines.append(b"%s: %s" % (k, v))
    lines.append(b"")
    lines.append(b"")
    http_request = b"\r\n".join(lines)
    log("client_upgrade: sending http headers: %s", headers)
    now = monotonic()
    while http_request and monotonic()-now<MAX_WRITE_TIME:
        w = write(http_request)
        http_request = http_request[w:]

    now = monotonic()
    response = b""
    while ("sec-websocket-protocol" not in u(response).lower()) and monotonic()-now<MAX_READ_TIME:
        response += read(READ_CHUNK_SIZE)
    headers = parse_response_header(response)
    verify_response_headers(headers, key)
    log("client_upgrade: done")

def parse_response_header(response):
    #parse response:
    head = response.split(b"\r\n\r\n", 1)[0]
    lines = head.split(b"\r\n")
    headers = {}
    for line in lines:
        parts = line.split(b": ", 1)
        if len(parts)==2:
            headers[parts[0].lower()] = parts[1]
    return headers

def verify_response_headers(headers, key):
    log("verify_response_headers(%s)", headers)
    if not headers:
        raise Exception("no http headers found in response")
    upgrade = headers.get(b"upgrade", b"")
    if upgrade!=b"websocket":
        raise Exception("invalid http upgrade: '%s'" % upgrade)
    protocol = headers.get(b"sec-websocket-protocol", b"")
    if protocol!=b"binary":
        raise Exception("invalid websocket protocol: '%s'" % protocol)
    accept_key = headers.get(b"sec-websocket-accept", b"")
    if not accept_key:
        raise Exception("websocket accept key is missing")
    expected_key = make_websocket_accept_hash(key)
    if bytestostr(accept_key)!=bytestostr(expected_key):
        raise Exception("websocket accept key is invalid")
