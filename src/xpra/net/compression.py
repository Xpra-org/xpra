#!/usr/bin/env python
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
from xpra.os_util import memoryview_to_bytes


lz4_version = None
try:
    import lz4
    from lz4 import LZ4_compress, LZ4_uncompress        #@UnresolvedImport
    has_lz4 = True
    def lz4_compress(packet, level):
        return level | LZ4_FLAG, LZ4_compress(memoryview_to_bytes(packet))
    #try to figure out the version number:
    if hasattr(lz4, "VERSION"):
        lz4_version = lz4.VERSION
        if hasattr(lz4, "LZ4_VERSION"):
            lz4_version.append(lz4.LZ4_VERSION)
    elif hasattr(lz4, "__file__"):
        #hack it..
        import os.path
        f = lz4.__file__
        #ie: /usr/lib/python2.7/site-packages/lz4-0.7.0-py2.7-linux-x86_64.egg/lz4.so
        for x in f.split(os.path.sep):
            #ie: lz4-0.7.0-py2.7-linux-x86_64.egg
            if x.startswith("lz4-") and x.find("-py"):
                tmp = x.split("-")[1]
                #ie: "0.7.0"
                tmpv = []
                #stop if we hit non numeric chars
                try:
                    for x in tmp.split("."):
                        tmpv.append(int(x))
                except:
                    pass
                #we want at least two numbers first:
                if len(tmpv)>=2:
                    #ie: (0, 7, 0)
                    lz4_version = tuple(tmpv)
                    assert lz4_version>=(0, 7), "versions older than 0.7.0 are vulnerable and should not be used, see CVE-2014-4715"
except Exception as e:
    log("lz4 not found: %s", e)
    LZ4_uncompress = None
    has_lz4 = False
    def lz4_compress(packet, level):
        raise Exception("lz4 is not supported!")


lzo_version = None
try:
    import lzo
    has_lzo = True
    lzo_version = lzo.LZO_VERSION_STRING
    def lzo_compress(packet, level):
        return level | LZO_FLAG, lzo.compress(memoryview_to_bytes(packet))
    LZO_decompress = lzo.decompress
except Exception as e:
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
    caps = {
            "lz4"                   : use_lz4,
            "lzo"                   : use_lzo,
            "zlib"                  : use_zlib,
            "zlib.version"          : zlib.__version__,
           }
    if lzo_version:
        caps["lzo.version"] = lzo_version
    if lz4_version:
        caps["lz4.version"] = lz4_version
    return caps

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


def sanity_checks():
    if not use_lzo and not use_lz4:
        if not use_zlib:
            log.warn("Warning: all the compressors are disabled,")
            log.warn(" unless you have a gigabit connection or better, performance will suffer")
        else:
            log.warn("Warning: zlib is the only compressor enabled")
            log.warn(" install and enable lzo or lz4 support for better performance")


class Compressed(object):
    def __init__(self, datatype, data, can_inline=False):
        self.datatype = datatype
        self.data = data
        self.can_inline = can_inline
    def __len__(self):
        return len(self.data)
    def __repr__(self):
        return  "Compressed(%s: %s bytes)" % (self.datatype, len(self.data))


class LevelCompressed(Compressed):
    def __init__(self, datatype, data, level, algo, can_inline):
        Compressed.__init__(self, datatype, data, can_inline)
        self.level = level
        self.algorithm = algo
    def __repr__(self):
        return  "LevelCompressed(%s: %s bytes as %s/%s)" % (self.datatype, len(self.data), self.algorithm, self.level)


class Uncompressed(object):
    def __init__(self, datatype, data):
        self.datatype = datatype
        self.data = data
    def __len__(self):
        return len(self.data)
    def __repr__(self):
        return  "Uncompressed(%s: %s bytes)" % (self.datatype, len(self.data))
    def compress(self):
        raise Exception("compress() not defined on %s" % self)

def compressed_wrapper(datatype, data, level=5, zlib=False, lz4=False, lzo=False, can_inline=True):
    if lz4:
        assert use_lz4, "cannot use lz4"
        algo = "lz4"
        cl, cdata = lz4_compress(data, level)
    elif lzo:
        assert use_lzo, "cannot use lzo"
        algo = "lzo"
        cl, cdata = lzo_compress(data, level)
    else:
        assert use_zlib, "cannot use zlib"
        algo = "zlib"
        cl, cdata = zcompress(data, level)
    return LevelCompressed(datatype, cdata, cl, algo, can_inline=can_inline)


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


def main():
    from xpra.platform import init, clean
    try:
        init("Compression", "Compression Info")
        for k,v in sorted(get_compression_caps().items()):
            print(k.ljust(20)+": "+str(v))
    finally:
        #this will wait for input on win32:
        clean()


if __name__ == "__main__":
    main()
