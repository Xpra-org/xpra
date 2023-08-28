#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections import namedtuple
from typing import Any, Tuple, Dict, Callable

from xpra.util import envbool
from xpra.common import MIN_COMPRESS_SIZE, MAX_DECOMPRESSED_SIZE


# all the compressors we know about, in the best compatibility order:
ALL_COMPRESSORS : Tuple[str, ...] = ("lz4", "zlib", "brotli", "none")
# order for performance:
PERFORMANCE_ORDER : Tuple[str, ...] = ("none", "lz4", "zlib", "brotli")
# require compression (disallow 'none'):
PERFORMANCE_COMPRESSION : Tuple[str, ...] = ("lz4", "zlib", "brotli")

Compression = namedtuple("Compression", ["name", "version", "compress", "decompress"])

COMPRESSION : Dict[str,Compression] = {}


def init_lz4() -> Compression:
    #pylint: disable=import-outside-toplevel
    #pylint: disable=redefined-outer-name
    from xpra.net.lz4.lz4 import compress, decompress, get_version  # @UnresolvedImport
    from xpra.net.protocol.header import LZ4_FLAG
    def lz4_compress(packet, level):
        flag = min(15, level) | LZ4_FLAG
        return flag, compress(packet, acceleration=max(0, 5-level//3))
    def lz4_decompress(data):
        return decompress(data, max_size=MAX_DECOMPRESSED_SIZE)
    return Compression("lz4", get_version(), lz4_compress, lz4_decompress)

def init_brotli() -> Compression:
    #pylint: disable=import-outside-toplevel
    #pylint: disable=redefined-outer-name
    from xpra.net.protocol.header import BROTLI_FLAG
    from xpra.net.brotli.compressor import compress, get_version  # @UnresolvedImport
    from xpra.net.brotli.decompressor import decompress  # @UnresolvedImport
    brotli_decompress = decompress
    brotli_compress = compress
    brotli_version = get_version()
    def brotli_compress_shim(packet, level):
        if len(packet)>1024*1024:
            level = min(9, level)
        else:
            level = min(11, level)
        if not isinstance(packet, (bytes, bytearray, memoryview)):
            packet = bytes(str(packet), 'UTF-8')
        return level | BROTLI_FLAG, brotli_compress(packet, quality=level)
    return Compression("brotli", brotli_version, brotli_compress_shim, brotli_decompress)

def init_zlib() -> Compression:
    #pylint: disable=import-outside-toplevel
    import zlib
    from xpra.net.protocol.header import ZLIB_FLAG
    def zlib_compress(packet, level):
        level = min(9, max(1, level))
        if not isinstance(packet, (bytes, bytearray, memoryview)):
            packet = bytes(str(packet), 'UTF-8')
        return level + ZLIB_FLAG, zlib.compress(packet, level)
    def zlib_decompress(data):
        d = zlib.decompressobj()
        v = d.decompress(data, MAX_DECOMPRESSED_SIZE)
        assert not d.unconsumed_tail, "not all data was decompressed"
        return v
    return Compression("zlib", zlib.__version__, zlib_compress, zlib_decompress)  # type: ignore[attr-defined]

def init_none() -> Compression:
    def nocompress(packet, _level):
        if not isinstance(packet, bytes):
            packet = bytes(str(packet), 'UTF-8')
        return 0, packet
    def nodecompress(v):
        return v
    return Compression("none", None, nocompress, nodecompress)


def init_compressors(*names) -> None:
    for x in names:
        assert x not in ("compressors", "all"), "attempted to recurse!"
        if not envbool("XPRA_"+x.upper(), True):
            continue
        attr = globals().get(f"init_{x}", None)
        if attr is None:
            from xpra.log import Logger
            logger = Logger("network", "protocol")
            logger.warn(f"Warning: invalid compressor {x} specified")
            continue
        try:
            if not callable(attr):
                raise ValueError(f"{attr!r} is not callable")
            fn : Callable = attr
            c = fn()
            assert c
            COMPRESSION[x] = c
        except (TypeError, ImportError, AttributeError):
            # pylint: disable=import-outside-toplevel
            from xpra.log import Logger
            logger = Logger("network", "protocol")
            logger(f"no {x}", exc_info=True)

def init_all() -> None:
    init_compressors(*(list(ALL_COMPRESSORS)+["none"]))


def use(compressor) -> bool:
    return compressor in COMPRESSION


def get_compression_caps(full_info : int=1) -> Dict[str,Any]:
    caps : Dict[str,Any] = {}
    for x in ALL_COMPRESSORS:
        c = COMPRESSION.get(x)
        if c is None:
            continue
        ccaps = caps.setdefault(x, {})
        if full_info>1 and c.version:
            ccaps["version"] = c.version
        ccaps[""] = True
    return caps

def get_enabled_compressors(order=ALL_COMPRESSORS) -> Tuple[str,...]:
    return tuple(x for x in order if x in COMPRESSION)

def get_compressor(name) -> Callable:
    c = COMPRESSION.get(name)
    if c is not None:
        return c.compress
    raise ValueError(f"{name!r} compression is not supported")


class Compressed:
    __slots__ = ("datatype", "data", "can_inline")
    def __init__(self, datatype, data, can_inline=False):
        assert data is not None, "compressed data cannot be set to None"
        self.datatype = datatype
        self.data = data
        self.can_inline = can_inline
    def __len__(self):
        return len(self.data)
    def __repr__(self):
        return f"Compressed({self.datatype}: {len(self.data)} bytes)"


class LevelCompressed(Compressed):
    __slots__ = ("level", "algorithm")
    def __init__(self, datatype, data, level, algo, can_inline):
        super().__init__(datatype, data, can_inline)
        self.level = level
        self.algorithm = algo
    def __repr__(self):
        return f"LevelCompressed({self.datatype}: {len(self.data)} bytes as {self.algorithm}/{self.level}"


class LargeStructure:
    __slots__ = ("datatype", "data")
    def __init__(self, datatype, data):
        self.datatype = datatype
        self.data = data
    def __len__(self):
        return len(self.data)
    def __repr__(self):
        return f"LargeStructure({self.datatype}: {len(self.data)} bytes)"

class Compressible(LargeStructure):
    __slots__ = ()
    #wrapper for data that should be compressed at some point,
    #to use this class, you must override compress()
    def __repr__(self):
        return f"Compressible({self.datatype}: {len(self.data)} bytes)"
    def compress(self):
        raise NotImplementedError(f"compress() function is not defined on {self} ({type(self)})")


def compressed_wrapper(datatype, data, level=5, can_inline=True, **kwargs) -> Compressed:
    size = len(data)
    def no():
        return Compressed(f"raw {datatype}", data, can_inline=can_inline)
    if size<=MIN_COMPRESS_SIZE:
        #don't bother
        return no()
    if size>MAX_DECOMPRESSED_SIZE:
        sizemb = size//1024//1024
        maxmb = MAX_DECOMPRESSED_SIZE//1024//1024
        raise ValueError(f"uncompressed data is too large: {sizemb}MB, limit is {maxmb}MB")
    try:
        algo = next(x for x in PERFORMANCE_COMPRESSION if kwargs.get(x) and x in COMPRESSION)
    except StopIteration:
        return no()
        #raise InvalidCompressionException("no compressors available")
    #should use a smarter selection of algo based on datatype
    #ie: 'text' -> brotli
    c = COMPRESSION[algo]
    cl, cdata = c.compress(data, level)
    min_saving = kwargs.get("min_saving", 0)
    if len(cdata)>=size+min_saving:
        return no()
    return LevelCompressed(datatype, cdata, cl, algo, can_inline=can_inline)


class InvalidCompressionException(Exception):
    pass


def get_compression_type(level) -> str:
    from xpra.net.protocol.header import LZ4_FLAG, BROTLI_FLAG
    if level & LZ4_FLAG:
        return "lz4"
    if level & BROTLI_FLAG:
        return "brotli"
    return "zlib"


def decompress(data:bytes, level:int):
    from xpra.net.protocol.header import LZ4_FLAG, BROTLI_FLAG
    if level & LZ4_FLAG:
        algo = "lz4"
    elif level & BROTLI_FLAG:
        algo = "brotli"
    else:
        algo = "zlib"
    return decompress_by_name(data, algo)

def decompress_by_name(data:bytes, algo:str):
    c = COMPRESSION.get(algo)
    if c is None:
        raise InvalidCompressionException(f"{algo} is not available")
    return c.decompress(data)


def main(): # pragma: no cover
    #pylint: disable=import-outside-toplevel
    from xpra.util import print_nested_dict
    from xpra.platform import program_context
    with program_context("Compression", "Compression Info"):
        init_all()
        print_nested_dict(get_compression_caps())


if __name__ == "__main__":  # pragma: no cover
    main()
