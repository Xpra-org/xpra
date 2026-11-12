#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.net.common import Packet
from xpra.net.protocol.check import packet_structure_error, verify_packet


class TestVerifyPacket(unittest.TestCase):

    def test_none(self):
        assert not verify_packet(None)

    def test_empty_packet(self):
        # falsy value
        assert not verify_packet([])

    def test_not_a_packet_instance(self):
        # a plain list is not a Packet
        assert not verify_packet(["hello", "arg"])

    def test_valid_packet(self):
        assert verify_packet(Packet("test", "arg"))

    def test_nested_none(self):
        # None nested inside a valid packet structure
        p = Packet("test", [None])
        assert not verify_packet(p)

    def test_structure_limits(self):
        with patch("xpra.net.protocol.check.MAX_PACKET_NESTING", 3):
            self.assertIn("nesting", packet_structure_error(Packet("test", [[[[1]]]])))
        with patch("xpra.net.protocol.check.MAX_PACKET_CONTAINER_ITEMS", 2):
            self.assertIn("container", packet_structure_error(Packet("test", [1, 2, 3])))
        with patch("xpra.net.protocol.check.MAX_PACKET_NODES", 3):
            self.assertIn("values", packet_structure_error(Packet("test", [1, 2, 3])))
        with patch("xpra.net.protocol.check.MAX_PACKET_TEXT_SIZE", 3):
            self.assertIn("string", packet_structure_error(Packet("test", "1234")))

    def test_unsupported_nested_type(self):
        self.assertIn("unsupported", packet_structure_error(Packet("test", [1.5])))

    def test_aliased_container(self):
        shared = [1]
        self.assertIn("aliased", packet_structure_error(Packet("test", [shared, shared])))
        self.assertEqual(packet_structure_error(Packet("test", [(), ()])), "")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
