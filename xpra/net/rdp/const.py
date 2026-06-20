# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Constants for the lower layers of the RDP protocol:
 * TPKT (RFC 1006)
 * X.224 / COTP (ISO 8073) transport
 * the RDP negotiation structures (MS-RDPBCGR section 2.2.1.1/2.2.1.2)

This is just enough to parse and format the initial connection handshake,
not a full RDP implementation.
"""

from enum import IntEnum, IntFlag

# TPKT (RFC 1006) header is: version(1), reserved(1), length(2, big-endian)
TPKT_VERSION = 3
TPKT_HEADER_SIZE = 4


class X224(IntEnum):
    """ X.224 / COTP TPDU codes (the high nibble of the type byte) """
    CR = 0xE0   # Connection Request
    CC = 0xD0   # Connection Confirm
    DR = 0x80   # Disconnect Request
    DT = 0xF0   # Data
    ER = 0x70   # Error


# the fixed part of an X.224 CR / CC TPDU header that follows the LI octet:
# code(1) + dst-ref(2) + src-ref(2) + class-option(1)
X224_CR_CC_FIXED_SIZE = 6


class RDPNeg(IntEnum):
    """ type field of the RDP negotiation structures """
    REQUEST = 0x01      # RDP_NEG_REQ
    RESPONSE = 0x02     # RDP_NEG_RSP
    FAILURE = 0x03      # RDP_NEG_FAILURE


# all three RDP negotiation structures are 8 bytes:
# type(1), flags(1), length(2, little-endian)=8, payload(4, little-endian)
RDP_NEG_SIZE = 8


class SecurityProtocol(IntFlag):
    """ security protocols advertised (requestedProtocols) or chosen (selectedProtocol) """
    RDP = 0x00000000        # standard RDP security
    SSL = 0x00000001        # TLS 1.x
    HYBRID = 0x00000002     # CredSSP / NLA (implies SSL)
    RDSTLS = 0x00000004
    HYBRID_EX = 0x00000008
    RDSAAD = 0x00000010


class RDPNegFailure(IntEnum):
    """ failureCode values for RDP_NEG_FAILURE """
    SSL_REQUIRED_BY_SERVER = 1
    SSL_NOT_ALLOWED_BY_SERVER = 2
    SSL_CERT_NOT_ON_SERVER = 3
    INCONSISTENT_FLAGS = 4
    HYBRID_REQUIRED_BY_SERVER = 5
    SSL_WITH_USER_AUTH_REQUIRED_BY_SERVER = 6


def protocols_str(value: int) -> str:
    """ human-readable representation of a requestedProtocols / selectedProtocol bitmask """
    if value == 0:
        return "RDP"
    names = []
    for flag in SecurityProtocol:
        if flag != SecurityProtocol.RDP and value & flag:
            names.append(flag.name)
    leftover = value & ~int(sum(SecurityProtocol))
    if leftover:
        names.append(f"{leftover:#x}")
    return "|".join(names) if names else f"{value:#x}"
