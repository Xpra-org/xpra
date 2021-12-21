#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net import compression

class TestCompression(unittest.TestCase):

    def test_main(self):
        compression.init_all()
        assert compression.use("zlib")
        assert compression.get_compression_caps()
        assert compression.get_enabled_compressors()
        for x in compression.get_enabled_compressors():
            assert compression.get_compressor(x)

    def _test_wrapper_class(self, clazz):
        for data in (b"hello", memoryview(b"foo")):
            x = clazz("datatype", data)
            assert repr(x)
            assert len(x)==len(data)
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
                raise Exception("%s is not a valid compression" % x)

    def test_compressed_wrapper(self):
        r = compression.compressed_wrapper("test", b"a"*(compression.MIN_COMPRESS_SIZE+1))
        if not r.datatype.startswith("raw"):
            raise Exception("should not be able to use the wrapper without enabling a compressor, but got %s" % r)
        for x in ("lz4", "brotli", "zlib", "none"):
            if not compression.use(x):
                continue
            kwargs = {x : True}
            for level in (0, 1, 5, 10):
                for data in (
                    b"0"*1024,
                    b"0"*16,
                    b"\0",
                    memoryview(b"hello"),
                    bytearray(b"hello"),
                    b"1"*1024*1024*16,
                    ):
                    v = compression.compressed_wrapper("test", data, level=level, **kwargs)
                    assert v
                    assert repr(v)
                    assert compression.get_compression_type(v.level)
                    #and back:
                    try:
                        d = compression.decompress_by_name(v.data, v.algorithm)
                        assert d
                        if x!="none":
                            #we can't do none,
                            #because it would be mistaken for "zlib"
                            #(for historical reasons - 'zlib' uses level=0, and 'none' has no level)
                            d = compression.decompress(v.data, v.level)
                            assert d
                    except Exception:
                        print("error decompressing %s - generated with settings: %s" % (v, kwargs))
                        raise

def main():
    unittest.main()

if __name__ == '__main__':
    main()
