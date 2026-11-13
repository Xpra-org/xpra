#!/usr/bin/env python3
# ABOUTME: OSS-Fuzz / Atheris harness for the xpra packet header parsing and validation,
# ABOUTME: including the header search used when a connection is not yet in sync.

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# https://github.com/Xpra-org/xpra/issues/5148

import sys

import atheris

with atheris.instrument_imports():
    from xpra.net.protocol.header import (
        HEADER_SIZE, unpack_header, pack_header, validate_packet_header, find_xpra_header,
    )


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    index = fdp.ConsumeIntInRange(0, 255)
    max_data_size = fdp.ConsumeIntInRange(0, 2 ** 32)
    buf = fdp.ConsumeBytes(fdp.remaining_bytes())

    if len(buf) >= HEADER_SIZE:
        pchar, flags, compression, packet_index, data_size = unpack_header(buf)
        for modern in (False, True):
            error = validate_packet_header(flags, compression, packet_index, modern=modern)
            assert isinstance(error, str), f"validate_packet_header returned {error!r}"
        # the header must survive a round trip:
        packed = pack_header(flags, compression, packet_index, data_size)
        assert unpack_header(packed) == (b"P", flags, compression, packet_index, data_size)

    pos = find_xpra_header(buf, index, max_data_size)
    if pos >= 0:
        # whatever we find must be a valid header for the requested index:
        assert pos + HEADER_SIZE <= len(buf), f"header at {pos} overflows {len(buf)} bytes"
        pchar, flags, compression, packet_index, data_size = unpack_header(buf[pos:pos + HEADER_SIZE])
        assert pchar == b"P"
        assert packet_index == index
        assert data_size < max_data_size
        assert not validate_packet_header(flags, compression, packet_index)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
