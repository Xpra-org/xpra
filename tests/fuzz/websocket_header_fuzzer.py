#!/usr/bin/env python3
# ABOUTME: OSS-Fuzz / Atheris harness for the websocket frame decoder
# ABOUTME: and its native unmasking code, reachable before authentication.

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# https://github.com/Xpra-org/xpra/issues/5148

import sys

import atheris

with atheris.instrument_imports():
    from xpra.net.websockets.header import decode_hybi


def TestOneInput(data: bytes) -> None:
    parsed = decode_hybi(data)
    if parsed is None:
        return
    opcode, payload, length, fin = parsed
    assert 0 <= opcode <= 0x0f
    assert isinstance(fin, bool)
    assert length <= len(data), f"frame length {length} exceeds buffer size {len(data)}"
    assert len(payload) < length, f"payload size {len(payload)} vs frame length {length}"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
