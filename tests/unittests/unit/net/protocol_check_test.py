#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.common import Packet
from xpra.net.protocol.check import verify_packet


class TestVerifyPacket(unittest.TestCase):

    def test_none(self):
        assert not verify_packet(None)

    def test_empty_packet(self):
        # falsy value
        assert not verify_packet([])

    def test_not_a_packet_instance(self):
        # a plain list is not a Packet
        assert not verify_packet(["hello", "arg"])

    def test_non_string_type(self):
        # bypass Packet constructor to put a non-string at index 0
        p = Packet("test", "arg")
        p.data[0] = 123
        assert not verify_packet(p)

    def test_valid_packet(self):
        assert verify_packet(Packet("test", "arg"))

    def test_nested_none(self):
        # None nested inside a valid packet structure
        p = Packet("test", "arg")
        p.data.append(None)
        assert not verify_packet(p)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
