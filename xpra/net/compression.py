#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

from xpra.os_util import PYTHON3
from xpra.net.header import LZ4_FLAG, ZLIB_FLAG, LZO_FLAG, BROTLI_FLAG


def debug(msg, *args, **kwargs):
    from xpra.log import Logger
    logger = Logger("network", "protocol")
    logger.debug(msg, *args, **kwargs)


MAX_SIZE = 256*1024*1024


python_lz4_version = None
lz4_version = None
has_lz4 = False
def no_lz4(packet, level):
    raise Exception("lz4 is not supported!")
lz4_compress = no_lz4
try:
    from lz4 import VERSION as python_lz4_version   #@UnresolvedImport
    from lz4.version import version as lz4_version
    from lz4.block import compress, decompress as LZ4_uncompress
    python_lz4_version = python_lz4_version.encode("latin1")
    has_lz4 = True
    def lz4_block_compress(packet, level):
        flag = min(15, level) | LZ4_FLAG
        if level>=7:
            return flag, compress(packet, mode="high_compression", compression=level)
        if level<=3:
            return flag, compress(packet, mode="fast", acceleration=8-level*2)
        return flag, compress(packet)
    lz4_compress = lz4_block_compress
except Exception as e:
    debug("lz4 not found", exc_info=True)
    del e
    LZ4_uncompress = None

python_lzo_version = None
lzo_version = None
try:
    import lzo as python_lzo      #@UnresolvedImport
    has_lzo = True
    python_lzo_version = python_lzo.__version__
    lzo_version = python_lzo.LZO_VERSION_STRING
    def lzo_compress(packet, level):
        if isinstance(packet, memoryview):
            packet = packet.tobytes()
        return level | LZO_FLAG, python_lzo.compress(packet)
    LZO_decompress = python_lzo.decompress
except Exception as e:
    debug("lzo not found: %s", e)
    del e
    LZO_decompress = None
    has_lzo = False
    def lzo_compress(packet, level):
        raise Exception("lzo is not supported!")


brotli_compress = None
brotli_decompress = None
brotli_version = None
try:
    from brotli import (
        compress as bcompress,
        decompress as bdecompress,
        __version__ as brotli_version,
        )
    has_brotli = True
    def _brotli_compress(packet, level):
        if len(packet)>1024*1024:
            level = min(9, level)
        else:
            level = min(11, level)
        if not isinstance(packet, bytes):
            packet = bytes(packet, 'UTF-8')
        return level | BROTLI_FLAG, bcompress(packet, quality=level)
    brotli_compress = _brotli_compress
    brotli_decompress = bdecompress
except ImportError:
    has_brotli = False


try:
    from zlib import compress as zlib_compress, decompress as zlib_decompress
    from zlib import __version__ as zlib_version
    has_zlib = True
    #stupid python version breakage:
    if PYTHON3:
        def zcompress(packet, level):
            if isinstance(packet, memoryview):
                packet = packet.tobytes()
            elif not isinstance(packet, bytes):
                packet = bytes(packet, 'UTF-8')
            return level + ZLIB_FLAG, zlib_compress(packet, level)
    else:
        def zcompress(packet, level):
            if isinstance(packet, memoryview):
                packet = packet.tobytes()
            else:
                packet = str(packet)
            return level + ZLIB_FLAG, zlib_compress(packet, level)
except ImportError:
    has_zlib = False
    def zcompress(packet, level):
        raise Exception("zlib is not supported!")


if PYTHON3:
    def nocompress(packet, _level):
        if not isinstance(packet, bytes):
            packet = bytes(packet, 'UTF-8')
        return 0, packet
else:
    def nocompress(packet, _level):
        return 0, packet


#defaults to True if available:
use_zlib = has_zlib
use_lzo = has_lzo
use_lz4 = has_lz4
use_brotli = has_brotli

#all the compressors we know about, in best compatibility order:
ALL_COMPRESSORS = ("zlib", "lz4", "lzo", "brotli")

#order for performance:
PERFORMANCE_ORDER = ("lz4", "lzo", "zlib", "brotli")


_COMPRESSORS = {
    "zlib"  : zcompress,
    "lz4"   : lz4_compress,
    "lzo"   : lzo_compress,
    "brotli": brotli_compress,
    "none"  : nocompress,
    }

def get_compression_caps():
    caps = {}
    _lzo = {"" : use_lzo}
    if lzo_version:
        _lzo["version"] = lzo_version
    if python_lzo_version:
        caps["python-lzo"] = {
                              ""            : True,
                              "version"     : python_lzo_version,
                              }
    _lz4 = {""  : use_lz4}
    if lz4_version:
        _lz4["version"] = lz4_version
    if python_lz4_version:
        caps["python-lz4"] = {
                              ""            : True,
                              "version"     : python_lz4_version,
                              }
    _zlib = {
             ""             : use_zlib,
             }
    if has_zlib:
        _zlib["version"] = zlib_version
    _brotli = {
        ""                  : use_brotli
        }
    if has_brotli:
        _brotli["version"] = brotli_version
    caps.update({
        "lz4"                   : _lz4,
        "lzo"                   : _lzo,
        "zlib"                  : _zlib,
        "brotli"                : _brotli,
        })
    return caps

def get_enabled_compressors(order=ALL_COMPRESSORS):
    enabled = tuple(x for x,b in {
        "lz4"                   : use_lz4,
        "lzo"                   : use_lzo,
        "zlib"                  : use_zlib,
        "brotli"                : use_brotli,
        }.items() if b)
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


def sanity_checks():
    if not use_lzo and not use_lz4:
        from xpra.log import Logger
        logger = Logger("network", "protocol")
        if not use_zlib:
            logger.warn("Warning: all the compressors are disabled,")
            logger.warn(" unless you use mmap or have a gigabit connection or better")
            logger.warn(" performance will suffer")
        else:
            logger.warn("Warning: zlib is the only compressor enabled")
            logger.warn(" install and enable lz4 support for better performance")


class Compressed(object):
    def __init__(self, datatype, data, can_inline=False):
        assert data is not None, "compressed data cannot be set to None"
        self.datatype = datatype
        self.data = data
        self.can_inline = can_inline
    def __len__(self):
        return len(self.data)
    def __repr__(self):
        return  "Compressed(%s: %i bytes)" % (self.datatype, len(self.data))


class LevelCompressed(Compressed):
    def __init__(self, datatype, data, level, algo, can_inline):
        Compressed.__init__(self, datatype, data, can_inline)
        self.level = level
        self.algorithm = algo
    def __repr__(self):
        return  "LevelCompressed(%s: %i bytes as %s/%i)" % (self.datatype, len(self.data), self.algorithm, self.level)


class LargeStructure(object):
    def __init__(self, datatype, data):
        self.datatype = datatype
        self.data = data
    def __len__(self):
        return len(self.data)
    def __repr__(self):
        return  "LargeStructure(%s: %i bytes)" % (self.datatype, len(self.data))

class Compressible(LargeStructure):
    #wrapper for data that should be compressed at some point,
    #to use this class, you must override compress()
    def __repr__(self):
        return  "Compressible(%s: %i bytes)" % (self.datatype, len(self.data))
    def compress(self):
        raise Exception("compress() not defined on %s" % self)


def compressed_wrapper(datatype, data, level=5, zlib=False, lz4=False, lzo=False, brotli=False, can_inline=True):
    size = len(data)
    if size>MAX_SIZE:
        sizemb = size//1024//1024
        maxmb = MAX_SIZE//1024//1024
        raise Exception("uncompressed data is too large: %iMB, limit is %iMB" % (sizemb, maxmb))
    if lz4:
        assert use_lz4, "cannot use lz4"
        algo = "lz4"
        cl, cdata = lz4_compress(data, level)
    elif lzo:
        assert use_lzo, "cannot use lzo"
        algo = "lzo"
        cl, cdata = lzo_compress(data, level)
    elif brotli:
        assert use_brotli, "cannot use brotli"
        algo = "brotli"
        cl, cdata = brotli_compress(data, level)
    else:
        assert zlib and use_zlib, "cannot use zlib"
        algo = "zlib"
        cl, cdata = zcompress(data, level)
    return LevelCompressed(datatype, cdata, cl, algo, can_inline=can_inline)


class InvalidCompressionException(Exception):
    pass


def get_compression_type(level):
    if level & LZ4_FLAG:
        return "lz4"
    if level & LZO_FLAG:
        return "lzo"
    if level & BROTLI_FLAG:
        return "brotli"
    return "zlib"


LZ4_HEADER = struct.Struct(b'<L')
def decompress(data, level):
    #log.info("decompress(%s bytes, %s) type=%s", len(data), get_compression_type(level))
    if level & LZ4_FLAG:
        if not has_lz4:
            raise InvalidCompressionException("lz4 is not available")
        if not use_lz4:
            raise InvalidCompressionException("lz4 is not enabled")
        size = LZ4_HEADER.unpack_from(data[:4])[0]
        #it would be better to use the max_size we have in protocol,
        #but this hardcoded value will do for now
        if size>MAX_SIZE:
            sizemb = size//1024//1024
            maxmb = MAX_SIZE//1024//1024
            raise Exception("uncompressed data is too large: %iMB, limit is %iMB" % (sizemb, maxmb))
        return LZ4_uncompress(data)
    if level & LZO_FLAG:
        if not has_lzo:
            raise InvalidCompressionException("lzo is not available")
        if not use_lzo:
            raise InvalidCompressionException("lzo is not enabled")
        return LZO_decompress(data)
    if level & BROTLI_FLAG:
        if not has_brotli:
            raise InvalidCompressionException("brotli is not available")
        if not use_brotli:
            raise InvalidCompressionException("brotli is not enabled")
        return brotli_decompress(data)
    if not use_zlib:
        raise InvalidCompressionException("zlib is not enabled")
    if isinstance(data, memoryview):
        data = data.tobytes()
    return zlib_decompress(data)

NAME_TO_FLAG = {
    "lz4"   : LZ4_FLAG,
    "zlib"  : 0,
    "lzo"   : LZO_FLAG,
    "brotli": BROTLI_FLAG,
    }

def decompress_by_name(data, algo):
    assert algo in NAME_TO_FLAG, "invalid compression algorithm: %s" % algo
    flag = NAME_TO_FLAG[algo]
    return decompress(data, flag)


def main():
    from xpra.util import print_nested_dict
    from xpra.platform import program_context
    with program_context("Compression", "Compression Info"):
        print_nested_dict(get_compression_caps())


if __name__ == "__main__":
    main()
