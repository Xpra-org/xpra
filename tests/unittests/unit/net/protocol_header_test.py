#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.protocol.header import (
    BROTLI_FLAG,
    FLAGS_RENCODE,
    FLAGS_RENCODEPLUS,
    FLAGS_YAML,
    find_xpra_header,
    pack_header,
    unpack_header,
)


class ProtocolHeaderTest(unittest.TestCase):

    def test_pack_unpack_and_offsets(self):
        header = pack_header(FLAGS_RENCODE, 0, 0, 100)
        self.assertEqual(unpack_header(header), (b"P", FLAGS_RENCODE, 0, 0, 100))
        self.assertEqual(find_xpra_header(b"junk" + header), 4)
        self.assertEqual(find_xpra_header(b"junk" + header, index=1), -1)
        self.assertEqual(find_xpra_header(header, max_data_size=100), -1)

    def test_incomplete_and_false_candidates(self):
        valid = pack_header(0, 0, 0, 10)
        self.assertEqual(find_xpra_header(b"Pshort"), -1)
        self.assertEqual(find_xpra_header(pack_header(0, 0, 1, 10) + valid), 8)
        conflicting = pack_header(FLAGS_RENCODE | FLAGS_YAML, 0, 0, 10)
        self.assertEqual(find_xpra_header(conflicting + valid), len(conflicting))
        conflicting = pack_header(FLAGS_RENCODE | FLAGS_RENCODEPLUS, 0, 0, 10)
        self.assertEqual(find_xpra_header(conflicting), -1)

    def test_compression_validation(self):
        self.assertEqual(find_xpra_header(pack_header(0, BROTLI_FLAG | 1, 0, 10)), 0)
        self.assertEqual(find_xpra_header(pack_header(0, BROTLI_FLAG, 0, 10)), -1)


if __name__ == "__main__":
    unittest.main()
