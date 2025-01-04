#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest

from xpra.util.str_fn import Ellipsizer, memoryview_to_bytes as mtb
from xpra.log import consume_verbose_argv, Logger

log = Logger("lz4")


def e(s):
    return Ellipsizer(mtb(s))


INVALID_INPUTS = (None, True, 1, 1.2, [1, 2], (1, 2), object())


class TestLZ4(unittest.TestCase):

    def test_libversions(self):
        from xpra.net.lz4.lz4 import get_version  # @UnresolvedImport
        assert get_version() >= (1, 8)

    def td(self, v, match_value=None, maxsize=512 * 1024):
        log("tc%s", (Ellipsizer(v), Ellipsizer(match_value), maxsize))
        from xpra.net.lz4.lz4 import decompress  # @UnresolvedImport
        value = decompress(v, maxsize)
        if match_value is not None:
            assert mtb(value) == mtb(match_value), "expected %s but got %s" % (e(match_value), e(value))
        return value

    def fd(self, v, match_value=None, maxsize=512 * 1024):
        try:
            self.td(v, match_value, maxsize)
        except Exception:
            pass
        else:
            raise ValueError("decompression should have failed for %r" % v)

    def tc(self, v, match_value=None, level=2, maxsize=512 * 1024):
        log("tc%s", (Ellipsizer(v), Ellipsizer(match_value), level, maxsize))
        from xpra.net.lz4.lz4 import compress  # @UnresolvedImport
        value = compress(v, 10 - level)
        if match_value is not None:
            assert mtb(value) == mtb(match_value), "expected %s but got %s" % (e(match_value), e(value))
        return value

    def fc(self, v, match_value=None, maxsize=512 * 1024):
        try:
            self.tc(v, match_value, maxsize)
        except Exception:
            pass
        else:
            raise ValueError("compression should have failed for %r" % v)

    def test_decompressinvalidinput(self):
        for v in INVALID_INPUTS:
            self.fd(v)
        self.fd(b"hello")

    def test_decompressinputtoosmall(self):
        self.fd(b"hello")

    def test_decompressvalid(self):
        self.td(b"\x05\x00\x00\x00Phello", b"hello")

    def test_limit(self):
        br = b"".join((
            b"\x00\x00\x10\x00\x1f\x00\x01\x00",
            (b"\xff" * 4111),
            b"\xf6P\x00\x00\x00\x00\x00"))
        self.td(br, b"\0" * 1024 * 1024, 1024 * 1024)
        self.fd(br, b"\0" * 1024 * 1024, 1024 * 1024 - 1)

    def test_compress(self):
        for l in range(2, 11):
            self.tc(b"hello", b"\x05\x00\x00\x00Phello", l)

    def test_compressinvalidinput(self):
        for v in INVALID_INPUTS:
            self.fc(v)

    def test_roundtrip(self):
        TEST_INPUT = [b"hello", b"*" * 1024, b"+" * 64 * 1024]

        #find some real "text" files:

        def addf(path):
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    TEST_INPUT.append(f.read())

        if __file__:
            addf(__file__)
            path = os.path.abspath(os.path.dirname(__file__))
            while path:
                addf(os.path.join(path, "COPYING"))
                addf(os.path.join(path, "README.md"))
                parent_path = os.path.abspath(os.path.join(path, os.pardir))
                if parent_path == path or not parent_path:
                    break
                path = parent_path
        for l in range(2, 11):
            for v in TEST_INPUT:
                c = self.tc(v, level=l)
                self.td(c, v)


def main() -> None:
    consume_verbose_argv(sys.argv, "lz4")
    try:
        from xpra.net.lz4.lz4 import decompress, compress
        assert decompress and compress
    except ImportError as e:
        print("lz4 test skipped: %s" % e)
    else:
        unittest.main()


if __name__ == '__main__':
    main()
