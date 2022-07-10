#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
import binascii

from xpra.util import ellipsizer
from xpra.log import add_debug_category, enable_debug_for, Logger

log = Logger("brotli")


def b(s):
    return binascii.unhexlify(s.replace(" ", ""))

class TestBrotliDecompression(unittest.TestCase):

    def test_libversion(self):
        from xpra.net.brotli.decompressor import get_version
        v = get_version()
        assert v and len(v)==3
        assert v[0]>=1

    def t(self, v, match_value=None, maxsize=512*1024):
        log("t%s", (ellipsizer(v), ellipsizer(match_value), maxsize))
        from xpra.net.brotli.decompressor import decompress
        value = decompress(v, maxsize)
        if match_value is not None:
            assert value==match_value, "expected %s but got %s" % (match_value, value)
        return value

    def f(self, v, match_value=None, maxsize=512*1024):
        try:
            self.t(v, match_value, maxsize)
        except:
            pass
        else:
            raise ValueError("test should have failed for %r" % v)

    def test_invalidinput(self):
        self.f(None)
        self.f(True)
        self.f(1)
        self.f(1.2)
        self.f([1, 2])
        self.f((1, 2))
        self.f(b"hello")

    def test_inputtoosmall(self):
        self.f(b"hello")

    def test_valid(self):
        self.t(b("2110000468656c6c6f03"), b"hello")

    def test_1MBzeroes(self):
        br = b("59 ff ff 8f 5f 02 26 1e 0b 04 72 ef 1f 00")
        self.t(br, b"0"*1024*1024, 1024*1024)
        self.f(br, b"0"*1024*1024, 1024*1024-1)


def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        add_debug_category("brotli")
        enable_debug_for("brotli")
    try:
        from xpra.net.brotli import decompressor
        assert decompressor
    except ImportError as e:
        print("brotli test skipped: %s" % e)
    else:
        unittest.main()

if __name__ == '__main__':
    main()
