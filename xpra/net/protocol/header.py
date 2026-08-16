# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

# Note: since encoding flags and compression flags are all mutually exclusive,
# (ie: only one encoder and at most one compressor can be used at a time)
# we could theoretically add many more values here,
# not necessarily limiting ourselves to the ones that land on a bit.

# packet encoding flags:
FLAGS_BENCODE = 0x0  # assume bencode if not other flag is set
FLAGS_RENCODE = 0x1
FLAGS_YAML = 0x4
FLAGS_RENCODEPLUS = 0x10

# these flags can actually be combined with the encoders above:
FLAGS_FLUSH = 0x8
FLAGS_CIPHER = 0x2

# compression flags are carried in the "level" field,
# the low bits contain the compression level, the high bits the compression algo:
LZ4_FLAG = 0x10
# LZO_FLAG        = 0x20
BROTLI_FLAG = 0x40
ZSTD_FLAG = 0x80
FLAGS_NOHEADER = 0x10000  # never encoded, so we can use a value bigger than a byte

ENCODER_FLAGS = (FLAGS_RENCODE, FLAGS_YAML, FLAGS_RENCODEPLUS)
KNOWN_PROTOCOL_FLAGS = FLAGS_RENCODE | FLAGS_YAML | FLAGS_RENCODEPLUS | FLAGS_FLUSH | FLAGS_CIPHER
COMPRESSOR_FLAGS = (LZ4_FLAG, BROTLI_FLAG, ZSTD_FLAG)
KNOWN_COMPRESSOR_FLAGS = LZ4_FLAG | BROTLI_FLAG | ZSTD_FLAG

_header_unpack_struct = struct.Struct(b'!cBBBL')
HEADER_SIZE = _header_unpack_struct.size
assert HEADER_SIZE == 8


def unpack_header(buf) -> tuple:
    return _header_unpack_struct.unpack_from(buf)


# 'P' + protocol-flags + compression_level + packet_index + data_size
_header_pack_struct = struct.Struct(b'!BBBBL')
assert ord("P") == 80


def pack_header(proto_flags: int, level: int, index: int, payload_size: int) -> bytes:
    return _header_pack_struct.pack(80, proto_flags, level, index, payload_size)


def validate_packet_header(protocol_flags: int, compression: int, packet_index: int,
                           modern: bool = False) -> str:
    unknown_protocol_flags = protocol_flags & ~KNOWN_PROTOCOL_FLAGS
    if unknown_protocol_flags:
        return f"unknown protocol flags {unknown_protocol_flags:#x}"

    encoder_flags = protocol_flags & sum(ENCODER_FLAGS)
    encoder_count = sum(bool(encoder_flags & flag) for flag in ENCODER_FLAGS)
    if packet_index:
        if encoder_flags:
            return "raw packet chunks cannot specify an encoder"
        if protocol_flags & FLAGS_FLUSH:
            return "raw packet chunks cannot set the flush flag"
    elif modern:
        if encoder_count != 1 or encoder_flags & FLAGS_RENCODE:
            return "modern main packets must specify exactly one supported encoder"
    elif encoder_count > 1:
        return "main packets cannot specify more than one encoder"

    if compression:
        level = compression & 0x0f
        if level == 0:
            return "compressed packets must specify a non-zero compression level"
        compressor_flags = compression & 0xf0
        unknown_compressor_flags = compressor_flags & ~KNOWN_COMPRESSOR_FLAGS
        if unknown_compressor_flags:
            return f"unknown compressor flags {unknown_compressor_flags:#x}"
        compressor_count = sum(bool(compressor_flags & flag) for flag in COMPRESSOR_FLAGS)
        if compressor_count != 1:
            return "compressed packets must specify exactly one compressor"
    return ""


def find_xpra_header(data, index: int = 0, max_data_size: int = 2 ** 16) -> int:
    pos = data.find(b"P")
    while pos >= 0:
        if len(data) < pos + 8:
            # not enough data to try to parse this potential header
            return -1
        pchar, pflags, compress, packet_index, data_size = unpack_header(data[pos:pos + 8])
        valid = pchar == b"P" and packet_index == index and data_size < max_data_size
        if valid and not validate_packet_header(pflags, compress, packet_index):
            return pos
        # skip to the next potential header:
        pos = data.find(b"P", pos + 1)
    return -1
