#!/usr/bin/env python3
# ABOUTME: OSS-Fuzz / Atheris harness for the rencodeplus packet decoder,
# ABOUTME: which parses every packet a peer sends, including before authentication.

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# https://github.com/Xpra-org/xpra/issues/5148

import sys

import atheris

with atheris.instrument_imports():
    from xpra.net.rencodeplus.rencodeplus import loads, dumps

# the exceptions the network layer catches when decoding a packet,
# see `SocketProtocol.process_payload`:
EXPECTED = (ValueError, TypeError, IndexError)


def TestOneInput(data: bytes) -> None:
    try:
        value = loads(data)
    except EXPECTED:
        return
    # anything we managed to decode must be re-encodable:
    dumps(value)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
