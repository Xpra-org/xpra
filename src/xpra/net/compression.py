# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import zlib

from xpra.log import Logger
log = Logger("network", "protocol")
from xpra.net.header import LZ4_FLAG, ZLIB_FLAG, LZO_FLAG
from xpra.os_util import builtins


try:
    _memoryview = builtins.__dict__.get("memoryview")
    from lz4 import LZ4_compress, LZ4_uncompress        #@UnresolvedImport
    has_lz4 = True
    def lz4_compress(packet, level):
        if _memoryview and isinstance(packet, _memoryview):
            packet = packet.tobytes()
        return level + LZ4_FLAG, LZ4_compress(packet)
except Exception, e:
    log("lz4 not found: %s", e)
    LZ4_uncompress = None
    has_lz4 = False
    def lz4_compress(packet, level):
        raise Exception("lz4 is not supported!")


try:
    _memoryview = builtins.__dict__.get("memoryview")
    import lzo
    has_lzo = True
    def lzo_compress(packet, level):
        if _memoryview and isinstance(packet, _memoryview):
            packet = packet.tobytes()
        return level + LZO_FLAG, lzo.compress(packet)
    LZO_decompress = lzo.decompress
except Exception, e:
    log("lzo not found: %s", e)
    LZO_decompress = None
    has_lzo = False
    def lzo_compress(packet, level):
        raise Exception("lzo is not supported!")


#stupid python version breakage:
if sys.version > '3':
    def zcompress(packet, level):
        if type(packet)!=bytes:
            packet = bytes(packet, 'UTF-8')
        return level + ZLIB_FLAG, zlib.compress(packet, level)

    def nocompress(packet, level):
        if type(packet)!=bytes:
            packet = bytes(packet, 'UTF-8')
        return 0, packet
else:
    def zcompress(packet, level):
        return level + ZLIB_FLAG, zlib.compress(str(packet), level)
    def nocompress(packet, level):
        return 0, packet

#defaults to True if available:
use_zlib = True
use_lzo = has_lzo
use_lz4 = has_lz4

#all the compressors we know about, in best compatibility order:
ALL_COMPRESSORS = ["zlib", "lz4", "lzo"]

#order for performance:
PERFORMANCE_ORDER = ["lz4", "lzo", "zlib"]


_COMPRESSORS = {
        "zlib"  : zcompress,
        "lz4"   : lz4_compress,
        "lzo"   : lzo_compress,
        "none"  : nocompress,
               }

def get_compression_caps():
    return {
            "lz4"                   : use_lz4,
            "lzo"                   : use_lzo,
            "zlib"                  : use_zlib,
            "zlib.version"          : zlib.__version__,
           }

def get_enabled_compressors(order=ALL_COMPRESSORS):
    enabled = [x for x,b in {
            "lz4"                   : use_lz4,
            "lzo"                   : use_lzo,
            "zlib"                  : use_zlib,
            }.items() if b]
    #order them:
    return [x for x in order if x in enabled]

def get_compressor(c):
    assert c=="none" or c in ALL_COMPRESSORS
    return _COMPRESSORS[c]

def get_compressor_name(c):
    assert c in _COMPRESSORS.values(), "invalid compressor: %s" % c
    for k,v in _COMPRESSORS.items():
        if v==c:
            return k
    raise Exception("impossible bug!")


class Compressed(object):
    def __init__(self, datatype, data):
        self.datatype = datatype
        self.data = data
    def __len__(self):
        return len(self.data)
    def __repr__(self):
        return  "Compressed(%s: %s bytes)" % (self.datatype, len(self.data))


class LevelCompressed(Compressed):
    def __init__(self, datatype, data, level, algo):
        Compressed.__init__(self, datatype, data)
        self.algorithm = algo
        self.level = level
    def __len__(self):
        return len(self.data)
    def __repr__(self):
        return  "LevelCompressed(%s: %s bytes as %s/%s)" % (self.datatype, len(self.data), self.algorithm, self.level)


def compressed_wrapper(datatype, data, level=5, lz4=False):
    if lz4:
        assert use_lz4, "cannot use lz4"
        algo = "lz4"
        cl, cdata = lz4_compress(data, level & LZ4_FLAG)
    else:
        algo = "zlib"
        cl, cdata = zcompress(data, level)
    return LevelCompressed(datatype, cdata, cl, algo)


class InvalidCompressionException(Exception):
    pass


def get_compression_type(level):
    if level & LZ4_FLAG:
        return "lz4"
    elif level & LZO_FLAG:
        return "lzo"
    else:
        return "zlib"

def decompress(data, level):
    #log.info("decompress(%s bytes, %s) type=%s", len(data), get_compression_type(level))
    if level & LZ4_FLAG:
        if not has_lz4:
            raise InvalidCompressionException("lz4 is not available")
        if not use_lz4:
            raise InvalidCompressionException("lz4 is not enabled")
        return LZ4_uncompress(data)
    elif level & LZO_FLAG:
        if not has_lzo:
            raise InvalidCompressionException("lzo is not available")
        if not use_lzo:
            raise InvalidCompressionException("lzo is not enabled")
        return LZO_decompress(data)
    else:
        if not use_zlib:
            raise InvalidCompressionException("zlib is not enabled")
        return zlib.decompress(data)

NAME_TO_FLAG = {
                "lz4"   : LZ4_FLAG,
                "zlib"  : 0,
                "lzo"   : LZO_FLAG,
                }

def decompress_by_name(data, algo):
    assert algo in NAME_TO_FLAG, "invalid compression algorithm: %s" % algo
    flag = NAME_TO_FLAG[algo]
    return decompress(data, flag)
