# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Pure parsing and formatting of the RDP connection handshake:
TPKT framing, the X.224 Connection Request / Connection Confirm TPDUs,
and the RDP negotiation structures they carry.

These are plain functions with no I/O and no external dependencies,
so they can be unit-tested and reused by both the server and the client probe.
"""

from struct import pack, unpack_from
from dataclasses import dataclass

from xpra.net.rdp.const import (
    TPKT_VERSION, TPKT_HEADER_SIZE,
    X224, X224_CR_CC_FIXED_SIZE,
    RDPNeg, RDP_NEG_SIZE,
)

# X.224 CR/CC header following the LI octet: code(1) dst-ref(2) src-ref(2) class(1)
X224_CR_CC_STRUCT = b"!BBHHB"
# RDP negotiation structure: type(1) flags(1) length(2, LE) payload(4, LE)
RDP_NEG_STRUCT = b"<BBHI"


@dataclass
class ConnectionRequest:
    """ a parsed X.224 Connection Request and its optional RDP negotiation request """
    cookie: bytes = b""
    flags: int = 0
    requested_protocols: int = 0
    has_negotiation: bool = False


@dataclass
class NegotiationResponse:
    """ a parsed RDP_NEG_RSP or RDP_NEG_FAILURE from an X.224 Connection Confirm """
    type: int = 0
    flags: int = 0
    selected_protocol: int = 0
    failure_code: int = 0


# TPKT framing:

def parse_tpkt(buf) -> tuple[bytes, int]:
    """
    Extract a single complete TPKT PDU from `buf`.
    Returns (payload, total_length) where `total_length` includes the 4 byte header,
    or (b"", 0) when more data is required to complete the PDU.
    Raises ValueError on an invalid header.
    """
    if len(buf) < TPKT_HEADER_SIZE:
        return b"", 0
    version = buf[0]
    if version != TPKT_VERSION:
        raise ValueError(f"invalid TPKT version {version}, expected {TPKT_VERSION}")
    length = (buf[2] << 8) | buf[3]
    if length < TPKT_HEADER_SIZE:
        raise ValueError(f"invalid TPKT length {length}")
    if len(buf) < length:
        return b"", 0
    return bytes(buf[TPKT_HEADER_SIZE:length]), length


def format_tpkt(payload) -> bytes:
    length = TPKT_HEADER_SIZE + len(payload)
    if length > 0xFFFF:
        raise ValueError(f"TPKT payload too large: {len(payload)} bytes")
    return pack(b"!BBH", TPKT_VERSION, 0, length) + bytes(payload)


# X.224 Connection Request (client -> server):

def format_x224_connection_request(requested_protocols: int, cookie: bytes = b"") -> bytes:
    var = b""
    if cookie:
        var += b"Cookie: " + cookie + b"\r\n"
    var += pack(RDP_NEG_STRUCT, RDPNeg.REQUEST, 0, RDP_NEG_SIZE, requested_protocols)
    li = X224_CR_CC_FIXED_SIZE + len(var)
    return pack(X224_CR_CC_STRUCT, li, X224.CR, 0, 0, 0) + var


def parse_x224_connection_request(payload) -> ConnectionRequest:
    if len(payload) < 1 + X224_CR_CC_FIXED_SIZE:
        raise ValueError("X.224 Connection Request is too short")
    li = payload[0]
    code = payload[1] & 0xF0
    if code != X224.CR:
        raise ValueError(f"not an X.224 Connection Request (code {payload[1]:#x})")
    end = min(li + 1, len(payload))
    data = bytes(payload[1 + X224_CR_CC_FIXED_SIZE:end])
    cr = ConnectionRequest()
    # optional routingToken / cookie, terminated by CRLF:
    if data.startswith(b"Cookie:"):
        idx = data.find(b"\r\n")
        if idx >= 0:
            cr.cookie = data[:idx]
            data = data[idx + 2:]
    # optional RDP_NEG_REQ:
    if len(data) >= RDP_NEG_SIZE and data[0] == RDPNeg.REQUEST:
        _, flags, _, protocols = unpack_from(RDP_NEG_STRUCT, data, 0)
        cr.flags = flags
        cr.requested_protocols = protocols
        cr.has_negotiation = True
    return cr


# X.224 Connection Confirm (server -> client):

def format_rdp_neg_rsp(selected_protocol: int, flags: int = 0) -> bytes:
    return pack(RDP_NEG_STRUCT, RDPNeg.RESPONSE, flags, RDP_NEG_SIZE, selected_protocol)


def format_rdp_neg_failure(failure_code: int) -> bytes:
    return pack(RDP_NEG_STRUCT, RDPNeg.FAILURE, 0, RDP_NEG_SIZE, failure_code)


def format_x224_connection_confirm(negotiation: bytes = b"") -> bytes:
    li = X224_CR_CC_FIXED_SIZE + len(negotiation)
    return pack(X224_CR_CC_STRUCT, li, X224.CC, 0, 0, 0) + bytes(negotiation)


def parse_x224_connection_confirm(payload) -> NegotiationResponse | None:
    if len(payload) < 1 + X224_CR_CC_FIXED_SIZE:
        raise ValueError("X.224 Connection Confirm is too short")
    li = payload[0]
    code = payload[1] & 0xF0
    if code != X224.CC:
        raise ValueError(f"not an X.224 Connection Confirm (code {payload[1]:#x})")
    end = min(li + 1, len(payload))
    data = bytes(payload[1 + X224_CR_CC_FIXED_SIZE:end])
    if len(data) < RDP_NEG_SIZE:
        # a server that has no negotiation response falls back to standard RDP security:
        return None
    ntype, flags, _, value = unpack_from(RDP_NEG_STRUCT, data, 0)
    if ntype == RDPNeg.RESPONSE:
        return NegotiationResponse(ntype, flags, selected_protocol=value)
    if ntype == RDPNeg.FAILURE:
        return NegotiationResponse(ntype, flags, failure_code=value)
    return NegotiationResponse(ntype, flags)


# convenience wrappers returning complete TPKT framed PDUs:

def build_connection_request(requested_protocols: int, cookie: bytes = b"") -> bytes:
    return format_tpkt(format_x224_connection_request(requested_protocols, cookie))


def build_connection_confirm(negotiation: bytes = b"") -> bytes:
    return format_tpkt(format_x224_connection_confirm(negotiation))
