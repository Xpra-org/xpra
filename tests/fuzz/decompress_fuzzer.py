#!/usr/bin/env python3
# ABOUTME: OSS-Fuzz / Atheris harness for the native lz4, brotli and zstd decompressors,
# ABOUTME: which unpack compressed packets received from the network.

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# https://github.com/Xpra-org/xpra/issues/5148

import sys

import atheris

with atheris.instrument_imports():
    from xpra.net import compression
    from xpra.net.protocol.header import LZ4_FLAG, BROTLI_FLAG, ZSTD_FLAG

FLAGS = {
    "lz4": LZ4_FLAG,
    "brotli": BROTLI_FLAG,
    "zstd": ZSTD_FLAG,
}
compression.init_compressors(*FLAGS)
# `init_compressors` skips the ones that fail to load, don't fuzz without them:
if missing := tuple(name for name in FLAGS if name not in compression.COMPRESSION):
    raise RuntimeError(f"missing decompressors: {missing}")
LEVELS = tuple(FLAGS.values())

EXPECTED = (ValueError, compression.InvalidCompressionException)


def TestOneInput(data: bytes) -> None:
    if not data:
        return
    level = LEVELS[data[0] % len(LEVELS)] | 1
    # the network layer passes a memoryview of the receive buffer:
    payload = memoryview(data)[1:]
    try:
        out = compression.decompress(payload, level)
    except EXPECTED:
        return
    assert len(out) <= compression.MAX_DECOMPRESSED_SIZE, f"decompressed {len(out)} bytes"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
