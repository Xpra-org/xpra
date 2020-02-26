#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=line-too-long

import unittest

from xpra.net.header import (
    unpack_header, pack_header,
    FLAGS_BENCODE, FLAGS_RENCODE, FLAGS_CIPHER, FLAGS_YAML,
    ZLIB_FLAG, LZ4_FLAG, LZO_FLAG, BROTLI_FLAG,
    )

class TestPacketHeader(unittest.TestCase):

    def test_roundtrip(self):
        print("hello")
        for encode_flag in (FLAGS_BENCODE, FLAGS_RENCODE, FLAGS_YAML):
            for comp_flag in (ZLIB_FLAG, LZ4_FLAG, LZO_FLAG, BROTLI_FLAG):
                for cipher in (0, FLAGS_CIPHER):
                    for level in (0, 1, 10):
                        for index in (0, 1, 255):
                            for size in (0, 1, 2**8, 2**16, 2**24):
                                proto_flags = encode_flag | comp_flag | cipher
                                header = pack_header(proto_flags, level, index, size)
                                assert header
                                uproto_flags, ulevel, uindex, usize = unpack_header(header)[1:]
                                assert uproto_flags==proto_flags
                                assert ulevel==level
                                assert uindex==index
                                assert usize==size
                                for i in range(0, len(header)-1):
                                    try:
                                        unpack_header(header[:i])
                                    except Exception:
                                        pass
                                    else:
                                        raise Exception("header unpacking should have failed for size %i" % i)

def main():
    unittest.main()

if __name__ == '__main__':
    main()
