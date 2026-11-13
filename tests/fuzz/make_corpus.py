#!/usr/bin/env python3
# ABOUTME: Generates the seed corpus for the fuzz harnesses in this directory,
# ABOUTME: one sub-directory per harness, from valid packets produced by xpra's own encoders.

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# https://github.com/Xpra-org/xpra/issues/5148

import os
import sys
import struct
from hashlib import sha1
from collections.abc import Iterable

from xpra.net import compression
from xpra.net.rencodeplus.rencodeplus import dumps
from xpra.net.protocol.header import pack_header, FLAGS_RENCODEPLUS, FLAGS_FLUSH
from xpra.net.websockets.header import encode_hybi_header
from xpra.net.websockets.common import OPCODE

PACKETS = (
    ("hello", {"version": "6.5", "uuid": "0123456789abcdef", "encodings": ("rgb", "png", "jpeg")}),
    ("ping", 123456789, 0, ""),
    ("ping_echo", 123456789, 1, 2, 3, 4, "x"),
    ("disconnect", "timeout", "nothing received"),
    ("draw", 1, 0, 0, 64, 64, "rgb24", b"\0" * 64, 1, 256, {"compress": 1}),
    ("map-window", 1, -10, 20, 1920, 1080, {}),
    ("key-action", 1, "a", True, (), 97, "a", 38, 0),
    ("set-clipboard-enabled", False, ""),
    ("nested", [[[[1.5, -2, 2 ** 40, -2 ** 70, None, True]]]]),
)


def encoded_packets() -> Iterable[bytes]:
    for packet in PACKETS:
        yield dumps(packet)


def compressed(data: bytes) -> Iterable[tuple[int, bytes]]:
    for name in compression.get_enabled_compressors():
        if name == "none":
            continue
        level, cdata = compression.COMPRESSION[name].compress(data, 5)
        yield level, bytes(cdata)


def rencodeplus_seeds() -> Iterable[bytes]:
    yield from encoded_packets()


def decompress_seeds() -> Iterable[bytes]:
    # the first byte selects the decompressor, see `decompress_fuzzer.py`:
    algos = ("lz4", "brotli", "zstd")
    for data in encoded_packets():
        for name in compression.get_enabled_compressors():
            if name not in algos:
                continue
            _level, cdata = compression.COMPRESSION[name].compress(data, 5)
            yield bytes((algos.index(name), )) + bytes(cdata)


def datagram_seeds() -> Iterable[bytes]:
    for data in encoded_packets():
        yield pack_header(FLAGS_RENCODEPLUS, 0, 0, len(data)) + data
        for level, cdata in compressed(data):
            yield pack_header(FLAGS_RENCODEPLUS | FLAGS_FLUSH, level, 0, len(cdata)) + cdata


def header_seeds() -> Iterable[bytes]:
    # the first bytes are consumed as `index` and `max_data_size`, see `packet_header_fuzzer.py`:
    for seed in datagram_seeds():
        yield b"\0" + struct.pack("<I", 2 ** 16) + b"junk" + seed[:64]
    yield b"\1" + struct.pack("<I", 2 ** 20) + pack_header(0, 0, 1, 1024) + b"\0" * 16


def websocket_seeds() -> Iterable[bytes]:
    for seed in datagram_seeds():
        for mask in (False, True):
            header = encode_hybi_header(OPCODE.BINARY, len(seed), has_mask=mask)
            yield header + (b"\x12\x34\x56\x78" if mask else b"") + seed
    yield encode_hybi_header(OPCODE.PING, 0)
    yield encode_hybi_header(OPCODE.BINARY, 70000) + b"\0" * 70000


SEEDS = {
    "rencodeplus_fuzzer": rencodeplus_seeds,
    "decompress_fuzzer": decompress_seeds,
    "packet_datagram_fuzzer": datagram_seeds,
    "packet_header_fuzzer": header_seeds,
    "websocket_header_fuzzer": websocket_seeds,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} OUTPUT_DIRECTORY")
        return 1
    compression.init_compressors("lz4", "brotli", "zstd")
    for name, seeds in SEEDS.items():
        dirname = os.path.join(argv[1], name)
        os.makedirs(dirname, exist_ok=True)
        count = 0
        for seed in seeds():
            with open(os.path.join(dirname, sha1(seed).hexdigest()), "wb") as f:
                f.write(seed)
            count += 1
        print(f"{name}: {count} seeds")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
