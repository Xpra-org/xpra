#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable, Sequence, Sized
from dataclasses import dataclass

from xpra.util.env import envbool
from xpra.util.str_fn import memoryview_to_bytes
from xpra.common import MIN_COMPRESS_SIZE, MAX_DECOMPRESSED_SIZE, SizedBuffer

# all the compressors we know about:
ALL_COMPRESSORS: Sequence[str] = ("lz4", "zlib", "lzo", "brotli", "none")

VALID_COMPRESSORS: Sequence[str] = ("lz4", "brotli")

# the compressors we may want to use, in the best compatibility order:
TRY_COMPRESSORS: Sequence[str] = ("lz4", "brotli", "none")
# order for performance:
PERFORMANCE_ORDER: Sequence[str] = ("none", "lz4", "brotli")
# require compression (disallow 'none'):
PERFORMANCE_COMPRESSION: Sequence[str] = ("lz4", "brotli")


@dataclass
class Compression:
    name: str
    version: str
    compress: Callable[[SizedBuffer, int], tuple[int, SizedBuffer]]
    decompress: Callable[[SizedBuffer], SizedBuffer]


COMPRESSION: dict[str, Compression] = {}


def init_lz4() -> Compression:
    # pylint: disable=import-outside-toplevel
    # pylint: disable=redefined-outer-name
    from xpra.net.lz4.lz4 import compress, decompress, get_version  # @UnresolvedImport
    from xpra.net.protocol.header import LZ4_FLAG

    def lz4_compress(data: SizedBuffer, level: int) -> tuple[int, memoryview]:
        flag = min(15, level) | LZ4_FLAG
        return flag, compress(data, acceleration=max(0, 5 - level // 3))

    def lz4_decompress(data: SizedBuffer) -> memoryview:
        return decompress(data, max_size=MAX_DECOMPRESSED_SIZE)

    return Compression("lz4", get_version(), lz4_compress, lz4_decompress)


def init_brotli() -> Compression:
    # pylint: disable=import-outside-toplevel
    # pylint: disable=redefined-outer-name
    from xpra.net.protocol.header import BROTLI_FLAG
    from xpra.net.brotli.compressor import compress, get_version  # @UnresolvedImport
    from xpra.net.brotli.decompressor import decompress  # @UnresolvedImport
    brotli_decompress = decompress
    brotli_compress = compress
    brotli_version = get_version()

    def brotli_compress_shim(packet: SizedBuffer, level: int) -> tuple[int, memoryview]:
        if len(packet) > 1024 * 1024:
            level = min(9, level)
        else:
            level = min(11, level)
        if not isinstance(packet, (bytes, bytearray, memoryview)):
            packet = bytes(str(packet), 'UTF-8')
        return level | BROTLI_FLAG, brotli_compress(packet, quality=level)

    return Compression("brotli", brotli_version, brotli_compress_shim, brotli_decompress)


def init_none() -> Compression:

    def nocompress(data: SizedBuffer, _level) -> tuple[int, SizedBuffer]:
        if isinstance(data, bytes):
            return 0, data
        return 0, memoryview_to_bytes(data)

    def nodecompress(v: SizedBuffer) -> SizedBuffer:
        return v

    return Compression("none", "0", nocompress, nodecompress)


def init_compressors(*names: str) -> None:
    for x in names:
        assert x not in ("compressors", "all"), "attempted to recurse!"
        if not envbool("XPRA_" + x.upper(), True):
            continue
        attr = globals().get(f"init_{x}", None)
        if attr is None:
            from xpra.log import Logger
            logger = Logger("network", "protocol")
            logger.warn(f"Warning: invalid compressor {x} specified")
            continue
        try:
            if not callable(attr):
                raise ValueError(f"{attr!r} for {x} is not callable")
            fn: Callable = attr
            c = fn()
            assert c
            COMPRESSION[x] = c
        except (TypeError, ImportError, AttributeError):
            # pylint: disable=import-outside-toplevel
            from xpra.log import Logger
            logger = Logger("network", "protocol")
            logger(f"no {x}", exc_info=True)


def init_all() -> None:
    init_compressors(*(list(TRY_COMPRESSORS) + ["none"]))


def use(compressor) -> bool:
    return compressor in COMPRESSION


def get_compression_caps(full_info: int = 1) -> dict[str, Any]:
    caps: dict[str, Any] = {}
    for x in TRY_COMPRESSORS:
        c = COMPRESSION.get(x)
        if c is None:
            continue
        ccaps = caps.setdefault(x, {})
        if full_info > 1 and c.version:
            ccaps["version"] = c.version
        ccaps[""] = True
    return caps


def get_enabled_compressors(order=TRY_COMPRESSORS) -> Sequence[str]:
    return tuple(x for x in order if x in COMPRESSION)


def get_compressor(name: str) -> Callable:
    c = COMPRESSION.get(name)
    if c is not None:
        return c.compress
    raise ValueError(f"{name!r} compression is not supported")


class Compressed:
    __slots__ = ("datatype", "data", "can_inline")

    def __init__(self, datatype: str, data: SizedBuffer | Sequence, can_inline=True):
        if not data and not isinstance(data, Sequence):
            raise ValueError(f"missing compressed data, got {data!r} ({type(data)})")
        self.datatype = datatype
        self.data = data
        self.can_inline = can_inline

    def __len__(self):
        return len(self.data)

    def __repr__(self):
        return f"Compressed({self.datatype}: {len(self.data)} bytes)"


class LevelCompressed(Compressed):
    __slots__ = ("level", "algorithm")

    def __init__(self, datatype: str, data: SizedBuffer, level: int, algo: str, can_inline: bool):
        super().__init__(datatype, data, can_inline)
        self.level = level
        self.algorithm = algo

    def __repr__(self):
        return f"LevelCompressed({self.datatype}: {len(self.data)} bytes as {self.algorithm}/{self.level}"


class LargeStructure:
    __slots__ = ("datatype", "data")

    def __init__(self, datatype: str, data: Sized):
        self.datatype = datatype
        self.data = data

    def __len__(self):
        return len(self.data)

    def __repr__(self):
        return f"LargeStructure({self.datatype}: {len(self.data)} bytes)"


class Compressible(LargeStructure):
    __slots__ = ()

    # wrapper for data that should be compressed at some point,
    # to use this class, you must override compress()

    def __repr__(self):
        return f"Compressible({self.datatype}: {len(self.data)} bytes)"

    def compress(self):
        raise NotImplementedError(f"compress() function is not defined on {self} ({type(self)})")


def compressed_wrapper(datatype, data, level=5, can_inline=True, **kwargs) -> Compressed:
    size = len(data)

    def no() -> Compressed:
        return Compressed(f"raw {datatype}", data, can_inline=can_inline)

    if size <= MIN_COMPRESS_SIZE:
        # don't bother
        return no()
    if size > MAX_DECOMPRESSED_SIZE:
        sizemb = size // 1024 // 1024
        maxmb = MAX_DECOMPRESSED_SIZE // 1024 // 1024
        raise ValueError(f"uncompressed data is too large: {sizemb}MB, limit is {maxmb}MB")
    try:
        algo = next(x for x in PERFORMANCE_COMPRESSION if kwargs.get(x) and x in COMPRESSION)
    except StopIteration:
        return no()
        # raise InvalidCompressionException("no compressors available")
    # should use a smarter selection of algo based on datatype
    # ie: 'text' -> brotli
    c = COMPRESSION[algo]
    cl, cdata = c.compress(data, level)
    min_saving = int(kwargs.get("min_saving", 0))
    if len(cdata) >= size + min_saving:
        return no()
    return LevelCompressed(datatype, cdata, cl, algo, can_inline=can_inline)


class InvalidCompressionException(Exception):
    pass


def get_compression_type(level: int) -> str:
    from xpra.net.protocol.header import LZ4_FLAG, BROTLI_FLAG
    if level & LZ4_FLAG:
        return "lz4"
    if level & BROTLI_FLAG:
        return "brotli"
    return "zlib"


def decompress(data: bytes, level: int) -> SizedBuffer:
    from xpra.net.protocol.header import LZ4_FLAG, BROTLI_FLAG
    if level & LZ4_FLAG:
        algo = "lz4"
    elif level & BROTLI_FLAG:
        algo = "brotli"
    else:
        algo = "zlib"
    return decompress_by_name(data, algo)


def decompress_by_name(data: bytes, algo: str) -> SizedBuffer:
    c = COMPRESSION.get(algo)
    if c is None:
        raise InvalidCompressionException(f"{algo} is not available")
    return c.decompress(data)


def main():  # pragma: no cover
    # pylint: disable=import-outside-toplevel
    from xpra.util.str_fn import print_nested_dict
    from xpra.platform import program_context
    with program_context("Compression", "Compression Info"):
        init_all()
        print_nested_dict(get_compression_caps())


if __name__ == "__main__":  # pragma: no cover
    main()
