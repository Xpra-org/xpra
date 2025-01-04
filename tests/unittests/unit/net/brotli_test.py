#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest
import binascii

from xpra.util.str_fn import Ellipsizer
from xpra.log import Logger, consume_verbose_argv

log = Logger("brotli")


def b(s) -> bytes:
    return binascii.unhexlify(s.replace(" ", ""))


INVALID_INPUTS = (None, True, 1, 1.2, [1, 2], (1, 2), object())


# pylint: disable=import-outside-toplevel


class TestBrotli(unittest.TestCase):

    def test_libversions(self) -> None:
        from xpra.net.brotli import decompressor, compressor  # @UnresolvedImport
        for m in (decompressor, compressor):
            v = m.get_version()
            log("%s.get_version()=%s", m, v)
            assert v and len(v) == 3
            assert v[0] >= 1

    def td(self, v, match_value=None, maxsize=512 * 1024):
        log("tc%s", (Ellipsizer(v), Ellipsizer(match_value), maxsize))
        from xpra.net.brotli.decompressor import decompress  # @UnresolvedImport
        value = decompress(v, maxsize)
        if match_value is not None:
            assert value == match_value, f"expected {match_value!r} but got {value!r}"
        return value

    def fd(self, v, match_value=None, maxsize=512 * 1024):
        try:
            self.td(v, match_value, maxsize)
        except Exception:
            pass
        else:
            raise ValueError(f"decompression should have failed for {v!r}")

    def tc(self, v, match_value=None, level=2, maxsize=512 * 1024):
        log("tc%s", (Ellipsizer(v), Ellipsizer(match_value), level, maxsize))
        from xpra.net.brotli.compressor import compress  # @UnresolvedImport
        value = compress(v, level)
        if match_value is not None:
            assert value == match_value, f"expected {match_value!r} but got {value!r}"
        return value

    def fc(self, v, match_value=None, maxsize=512 * 1024):
        try:
            self.tc(v, match_value, maxsize)
        except Exception:
            pass
        else:
            raise ValueError(f"compression should have failed for {v!r}")

    def test_decompressinvalidinput(self):
        for v in INVALID_INPUTS:
            self.fd(v)
        self.fd(b"hello")

    def test_decompressinputtoosmall(self):
        self.fd(b"hello")

    def test_decompressvalid(self):
        self.td(b("2110000468656c6c6f03"), b"hello")

    def test_limit(self):
        br = b("59 ff ff 8f 5f 02 26 1e 0b 04 72 ef 1f 00")
        self.td(br, b"0" * 1024 * 1024, 1024 * 1024)
        self.fd(br, b"0" * 1024 * 1024, 1024 * 1024 - 1)

    def test_compress(self):
        for l in range(2, 11):
            self.tc(b"hello", b'\x0b\x02\x80hello\x03', l)

    def test_compressinvalidinput(self):
        for v in INVALID_INPUTS:
            self.fc(v)

    def test_roundtrip(self):
        TEST_INPUT = [b"hello", b"*" * 1024, b"+" * 64 * 1024]

        #find some real "text" files:

        def addf(path) -> None:
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
    consume_verbose_argv(sys.argv, "brotli")
    try:
        from xpra.net.brotli import decompressor, compressor
        assert decompressor and compressor
    except ImportError as e:
        print(f"brotli test skipped: {e}")
    else:
        unittest.main()


if __name__ == '__main__':
    main()
