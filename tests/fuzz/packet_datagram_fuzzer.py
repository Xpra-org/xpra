#!/usr/bin/env python3
# ABOUTME: OSS-Fuzz / Atheris harness for the full receive path of a single packet:
# ABOUTME: header validation, decompression and decoding, as for QUIC datagrams.

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# https://github.com/Xpra-org/xpra/issues/5148

import sys

import atheris

with atheris.instrument_imports():
    from xpra.net import compression, packet_encoding
    from xpra.net.common import Packet
    from xpra.net.protocol.socket_handler import SocketProtocol

COMPRESSORS = ("lz4", "brotli", "zstd")
compression.init_compressors(*COMPRESSORS)
packet_encoding.init_encoders("rencodeplus")
# the init functions skip the codecs that fail to load, don't fuzz without them:
if missing := tuple(name for name in COMPRESSORS if name not in compression.COMPRESSION):
    raise RuntimeError(f"missing decompressors: {missing}")
if "rencodeplus" not in packet_encoding.ENCODERS:
    raise RuntimeError("missing rencodeplus decoder")

EXPECTED = (
    ValueError, TypeError, IndexError,
    compression.InvalidCompressionException,
    packet_encoding.InvalidPacketEncodingException,
)


def TestOneInput(data: bytes) -> None:
    try:
        # `parse_datagram` does not use any instance state:
        packet = SocketProtocol.parse_datagram(None, data)
    except EXPECTED:
        return
    assert isinstance(packet, Packet)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
