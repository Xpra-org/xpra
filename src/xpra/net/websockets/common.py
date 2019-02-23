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
    b"Connection"               : "Upgrade",
    b"Upgrade"                  : "websocket",
    b"Sec-WebSocket-Version"    : "13",
    b"Sec-WebSocket-Protocol"   : "binary",
    }


def make_websocket_accept_hash(key):
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept = sha1(strtobytes(key + GUID)).digest()
    return b64encode(accept)

def client_upgrade(read, write, client_host):
    lines = [b"GET / HTTP/1.1"]
    key = b64encode(uuid.uuid4().bytes)
    headers = HEADERS.copy()
    headers[b"Sec-WebSocket-Key"] = key
    if client_host:
        headers[b"Host"] = client_host
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
    while response.find("Sec-WebSocket-Protocol")<0 and monotonic_time()-now<MAX_READ_TIME:
        response += read(READ_CHUNK_SIZE)
    headers = parse_response_header(response)
    verify_response_headers(headers, key)
    log("client_upgrade: done")

def parse_response_header(response):
    #parse response:
    head = response.split("\r\n\r\n", 1)[0]
    lines = head.split("\r\n")
    headers = {}
    for line in lines:
        parts = line.split(b": ", 1)
        if len(parts)==2:
            headers[parts[0]] = parts[1]
    return headers

def verify_response_headers(headers, key):
    log("verify_response_headers(%s)", headers)
    if not headers:
        raise Exception("no http headers found in response")
    upgrade = headers.get("Upgrade", b"")
    if upgrade!=b"websocket":
        raise Exception("invalid http upgrade: '%s'" % upgrade)
    protocol = headers.get("Sec-WebSocket-Protocol", b"")
    if protocol!=b"binary":
        raise Exception("invalid websocket protocol: '%s'" % protocol)
    accept_key = headers.get("Sec-WebSocket-Accept", b"")
    if not accept_key:
        raise Exception("websocket accept key is missing")
    expected_key = make_websocket_accept_hash(key)
    if bytestostr(accept_key)!=bytestostr(expected_key):
        raise Exception("websocket accept key is invalid")
