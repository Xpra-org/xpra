# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import zlib
import bz2

from xpra.log import Logger
log = Logger("network", "protocol")
debug = log.debug


ZLIB_FLAG = 0x00
LZ4_FLAG = 0x10
BZ2_FLAG = 0x20


try:
    from xpra.os_util import builtins
    _memoryview = builtins.__dict__.get("memoryview")
    from lz4 import LZ4_compress, LZ4_uncompress        #@UnresolvedImport
    has_lz4 = True
    def lz4_compress(packet, level):
        if _memoryview and isinstance(packet, _memoryview):
            packet = packet.tobytes()
        return level + LZ4_FLAG, LZ4_compress(packet)
except Exception, e:
    log("lz4 not found: %s", e)
    LZ4_compress, LZ4_uncompress = None, None
    has_lz4 = False
    def lz4_compress(packet, level):
        raise Exception("lz4 is not supported!")

#stupid python version breakage:
if sys.version > '3':
    def zcompress(packet, level):
        if type(packet)!=bytes:
            packet = bytes(packet, 'UTF-8')
        return level + ZLIB_FLAG, zlib.compress(packet, level)

    def bzcompress(packet, level):
        if type(packet)!=bytes:
            packet = bytes(packet, 'UTF-8')
        return level + BZ2_FLAG, bz2.compress(packet, level)

    def nocompress(packet, level):
        if type(packet)!=bytes:
            packet = bytes(packet, 'UTF-8')
        return 0, packet
else:
    def zcompress(packet, level):
        return level + ZLIB_FLAG, zlib.compress(str(packet), level)
    def bzcompress(packet, level):
        return level + BZ2_FLAG, bz2.compress(str(packet), level)
    def nocompress(packet, level):
        return 0, packet

#defaults to True if available:
use_zlib = True
use_bz2 = True
use_lz4 = has_lz4


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
