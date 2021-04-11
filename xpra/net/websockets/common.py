# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import uuid
from hashlib import sha1
from base64 import b64encode

from xpra.os_util import strtobytes, bytestostr, monotonic_time
from xpra.log import Logger

log = Logger("websocket")

MAX_WRITE_TIME = 5
MAX_READ_TIME = 5
READ_CHUNK_SIZE = 4096

HEADERS = {
    b"Connection"               : b"Upgrade",
    b"Upgrade"                  : b"websocket",
    b"Sec-WebSocket-Version"    : b"13",
    b"Sec-WebSocket-Protocol"   : b"binary",
    }


def make_websocket_accept_hash(key):
    GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept = sha1(strtobytes(key) + GUID).digest()
    return b64encode(accept)

def client_upgrade(read, write, host, port):
    lines = [b"GET / HTTP/1.1"]
    key = b64encode(uuid.uuid4().bytes)
    headers = HEADERS.copy()
    headers[b"Sec-WebSocket-Key"] = key
    if host:
        headers[b"Host"] = strtobytes("%s:%s" % (host, port))
    for k,v in headers.items():
        lines.append(b"%s: %s" % (k, v))
    lines.append(b"")
    lines.append(b"")
    http_request = b"\r\n".join(lines)
    log("client_upgrade: sending http headers: %s", headers)
    now = monotonic_time()
    while http_request and monotonic_time()-now<MAX_WRITE_TIME:
        w = write(http_request)
        http_request = http_request[w:]

    now = monotonic_time()
    response = b""
    while ("Sec-WebSocket-Protocol".lower() not in response.decode("utf-8").lower()) and monotonic_time()-now<MAX_READ_TIME:
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
