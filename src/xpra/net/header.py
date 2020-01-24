# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

#Note: since encoding flags and compression flags are all mutually exclusive,
# (ie: only one encoder and at most one compressor can be used at a time)
# we could theoretically add many more values here,
# not necessarily limitting ourselves to the ones that land on a bit.

#packet encoding flags:
FLAGS_BENCODE   = 0x0       #assume bencode if not other flag is set
FLAGS_RENCODE   = 0x1
FLAGS_CIPHER    = 0x2
FLAGS_YAML      = 0x4

#compression flags are carried in the "level" field,
#the low bits contain the compression level, the high bits the compression algo:
ZLIB_FLAG       = 0x0       #assume zlib if no other compression flag is set
LZ4_FLAG        = 0x10
LZO_FLAG        = 0x20
BROTLI_FLAG     = 0x40
FLAGS_NOHEADER  = 0x10000   #never encoded, so we can use a value bigger than a byte


_header_unpack_struct = struct.Struct(b'!cBBBL')
HEADER_SIZE = _header_unpack_struct.size
assert HEADER_SIZE==8

def unpack_header(buf):
    return _header_unpack_struct.unpack_from(buf)

#'P' + protocol-flags + compression_level + packet_index + data_size
_header_pack_struct = struct.Struct(b'!BBBBL')
assert ord("P") == 80
def pack_header(proto_flags, level, index, payload_size) -> bytes:
    return _header_pack_struct.pack(80, proto_flags, level, index, payload_size)
