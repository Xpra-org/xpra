# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from hashlib import sha1
from base64 import b64encode

from xpra.os_util import strtobytes, bytestostr, monotonic_time
from xpra.codecs.xor.cyxor import hybi_unmask
from xpra.log import Logger

log = Logger("websocket")


def make_websocket_accept_hash(key):
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept = sha1(strtobytes(key + GUID)).digest()
    return bytestostr(b64encode(accept))


def encode_hybi_header(opcode, payload_len, has_mask=False, fin=True):
    """ Encode a HyBi style WebSocket frame """
    assert (opcode & 0x0f)==opcode, "invalid opcode %#x" % opcode
    mask_bit = 0x80*has_mask
    b1 = opcode | (0x80 * fin)
    if payload_len <= 125:
        return struct.pack('>BB', b1, payload_len | mask_bit)
    if payload_len > 125 and payload_len < 65536:
        return struct.pack('>BBH', b1, 126 | mask_bit, payload_len)
    return struct.pack('>BBQ', b1, 127 | mask_bit, payload_len)


def decode_hybi_header(buf):
    """ Decode HyBi style WebSocket packets """
    blen = len(buf)
    hlen = 2
    if blen < hlen:
        #log("decode_hybi_header() buffer too small: %i", blen)
        return None

    b1, b2 = struct.unpack(">BB", buf[:2])
    opcode = b1 & 0x0f
    fin = bool(b1 & 0x80)
    masked = bool(b2 & 0x80)
    if masked:
        hlen += 4
        if blen < hlen:
            #log("decode_hybi_header() buffer too small for mask: %i", blen)
            return None

    payload_len = b2 & 0x7f
    if payload_len == 126:
        hlen += 2
        if blen < hlen:
            #log("decode_hybi_header() buffer too small for 126 payload: %i", blen)
            return None
        payload_len = struct.unpack('>H', buf[2:4])[0]
    elif payload_len == 127:
        hlen += 8
        if blen < hlen:
            #log("decode_hybi_header() buffer too small for 127 payload: %i", blen)
            return None
        payload_len = struct.unpack('>Q', buf[2:10])[0]

    #log("decode_hybi_header() decoded header '%s': hlen=%i, payload_len=%i, buffer len=%i", binascii.hexlify(buf[:hlen]), hlen, payload_len, blen)
    length = hlen + payload_len
    if blen < length:
        #log("decode_hybi_header() buffer too small for payload: %i (needed %i)", blen, length)
        return None

    if masked:
        payload = hybi_unmask(buf, hlen-4, payload_len)
    else:
        payload = buf[hlen:length]
    #log("decode_hybi_header() payload_len=%i, hlen=%i, length=%i, fin=%s", payload_len, hlen, length, fin)
    return opcode, payload, length, fin


def client_upgrade(conn):
    lines = [b"GET / HTTP/1.1"]
    import uuid
    import base64
    key = base64.b64encode(uuid.uuid4().bytes)
    headers = {
        b"Host"                     : "localhost:10000",
        b"Connection"               : "Upgrade",
        b"Upgrade"                  : "websocket",
        b"Sec-WebSocket-Version"    : "13",
        b"Sec-WebSocket-Protocol"   : "binary",
        b"Sec-WebSocket-Key"        : key,
        }
    for k,v in headers.items():
        lines.append(b"%s: %s" % (k, v))
    lines.append(b"")
    lines.append(b"")
    http_request = b"\r\n".join(lines)
    log("client_upgrade(%s) sending http headers: %s", conn, headers)
    now = monotonic_time()
    MAX_WRITE_TIME = 5
    while http_request and monotonic_time()-now<MAX_WRITE_TIME:
        w = conn.write(http_request)
        http_request = http_request[w:]

    now = monotonic_time()
    MAX_READ_TIME = 5
    response = b""
    while response.find("Sec-WebSocket-Protocol")<0 and monotonic_time()-now<MAX_READ_TIME:
        response += conn.read(4096)
    #parse response:
    head = response.split("\r\n\r\n", 1)[0]
    lines = head.split("\r\n")
    headers = {}
    for line in lines:
        parts = line.split(b": ", 1)
        if len(parts)==2:
            headers[parts[0]] = parts[1]
    log("client_upgrade(%s) got response headers=%s", conn, headers)
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
    if accept_key!=expected_key:
        raise Exception("websocket accept key is invalid")
    log("client_upgrade(%s) done", conn)
