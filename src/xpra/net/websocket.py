# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from hashlib import sha1
from base64 import b64encode

from xpra.os_util import strtobytes, bytestostr
from xpra.codecs.xor.cyxor import hybi_unmask


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
        return None

    b1, b2 = struct.unpack(">BB", buf[:2])
    opcode = b1 & 0x0f
    fin = bool(b1 & 0x80)
    masked = bool(b2 & 0x80)
    if masked:
        hlen += 4
        if blen < hlen:
            return None

    payload_len = b2 & 0x7f
    if payload_len == 126:
        hlen += 2
        if blen < hlen:
            return None
        payload_len = struct.unpack('>H', buf[2:4])[0]
    elif payload_len == 127:
        hlen += 8
        if blen < hlen:
            return None
        payload_len = struct.unpack('>Q', buf[2:10])[0]

    length = hlen + payload_len
    if blen < length:
        return None

    if masked:
        payload = hybi_unmask(buf, hlen-4, payload_len)
    else:
        payload = buf[hlen:length]
    return opcode, payload, length, fin
