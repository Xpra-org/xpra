#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net import compression


class TestCompression(unittest.TestCase):

    def test_main(self):
        compression.init_all()
        assert compression.use("lz4")
        assert compression.get_compression_caps()
        assert compression.get_enabled_compressors()
        for x in compression.get_enabled_compressors():
            assert compression.get_compressor(x)

    def _test_wrapper_class(self, clazz):
        for data in (b"hello", memoryview(b"foo")):
            x = clazz("datatype", data)
            assert repr(x)
            assert len(x) == len(data)
        x = clazz("fake", b"foo")
        assert repr(x)
        return x

    def test_compressed_class(self):
        self._test_wrapper_class(compression.Compressed)

    def test_large_structure(self):
        self._test_wrapper_class(compression.LargeStructure)

    def test_compressible(self):
        x = self._test_wrapper_class(compression.Compressible)
        try:
            x.compress()
        except Exception:
            pass
        else:
            raise Exception("compressible.compress must be overriden")

    def test_decompress_by_name(self):
        for x in ("foo", "lz4XX", "zli"):
            try:
                compression.decompress_by_name(b"foo", x)
            except Exception:
                pass
            else:
                raise Exception(f"{x} is not a valid compression")

    def test_compressed_wrapper(self):
        r = compression.compressed_wrapper("test", b"a" * max(1, (compression.MIN_COMPRESS_SIZE + 1)))
        if not r.datatype.startswith("raw"):
            raise Exception(f"should not be able to use the wrapper without enabling a compressor, but got {r!r}")
        for x in ("lz4", "brotli", "none"):
            if not compression.use(x):
                continue
            kwargs = {x: True}
            for level in (0, 1, 5, 10):
                for data in (
                        b"0" * 1024,
                        b"0" * 16,
                        b"\0",
                        memoryview(b"hello"),
                        bytearray(b"hello"),
                        b"1" * 1024 * 1024 * 16,
                ):
                    v = compression.compressed_wrapper("test", data, level=level, **kwargs)
                    assert v
                    assert repr(v)
                    assert compression.get_compression_type(v.level)
                    #and back:
                    try:
                        d = compression.decompress_by_name(v.data, v.algorithm)
                        assert d
                        if x != "none":
                            #we can't do none,
                            #because it would be mistaken for "zlib"
                            #(for historical reasons - 'zlib' uses level=0, and 'none' has no level)
                            d = compression.decompress(v.data, v.level)
                            assert d
                    except Exception:
                        print(f"error decompressing {v} - generated with settings: {kwargs}")
                        raise

    def test_lz4(self):
        try:
            from xpra.net.lz4.lz4 import compress, decompress
            from lz4 import block
        except ImportError as e:
            print(f"lz4 test skipped: {e}")
            return
        for t in (
                b"abc", b"foobar",
                b"\0" * 1000000,
        ):
            for accel in (0, 1, 5, 9):
                N = 1
                for _ in range(N):
                    c1 = compress(t, acceleration=accel)
                for _ in range(N):
                    c2 = block.compress(t, mode="fast", acceleration=accel)
                assert c1 == c2
                d1 = decompress(c1)
                d2 = block.decompress(c2)
                assert d1 == d2 == t


def main():
    unittest.main()


if __name__ == '__main__':
    main()
