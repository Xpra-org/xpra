#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.net import common, dispatch, packet_type
from xpra.net.common import Packet, legacy_peer
from xpra.net.dispatch import PacketDispatcher
from xpra.net.packet_type import LEGACY_PACKET_TYPES, get_packet_type_upgrades, get_legacy_packet_types
from xpra.net.protocol.socket_handler import SocketProtocol
from unit.test_util import silence_error


class PacketTypeTest(unittest.TestCase):

    def test_upgrades_by_role(self):
        client = get_packet_type_upgrades(False)
        server = get_packet_type_upgrades(True)
        # the legacy `screenshot` name is used for both the request and the response:
        self.assertEqual(client["screenshot"], "display-request-screenshot")
        self.assertEqual(server["screenshot"], "display-screenshot")
        # `encoding` sets the client's encoding, `encodings` is the server's list:
        self.assertEqual(client["encoding"], "encoding-set")
        self.assertNotIn("encoding", server)
        self.assertEqual(server["encodings"], "encoding-set")
        # older peers only know the legacy file transfer names:
        for upgrades in (client, server):
            self.assertEqual(upgrades["send-file"], "file-send")
            self.assertEqual(upgrades["ack-file-chunk"], "file-ack-chunk")

    def test_upgrades_do_not_chain(self):
        # a packet is renamed once: no modern name may also be a legacy name for the same sender
        for server in (False, True):
            upgrades = get_packet_type_upgrades(server)
            self.assertFalse(set(upgrades.keys()) & set(upgrades.values()))

    def test_legacy_packet_types(self):
        self.assertEqual(get_legacy_packet_types("display-resized"), ("desktop_size", ))
        self.assertIn("encodings", get_legacy_packet_types("encoding-set"))
        self.assertIn("encoding", get_legacy_packet_types("encoding-set"))
        self.assertEqual(get_legacy_packet_types("hello"), ())
        for legacy, modern, sender in LEGACY_PACKET_TYPES:
            self.assertNotEqual(legacy, modern)
            self.assertIn(sender, ("", "client", "server"))

    def test_legacy_peer(self):
        with patch.object(common, "BACKWARDS_COMPATIBLE", True):
            for legacy in ((), None, (5, 1), (6, 6)):
                self.assertTrue(legacy_peer(legacy), f"{legacy} should be a legacy peer")
            for modern in ((7, 0), (8, 0)):
                self.assertFalse(legacy_peer(modern), f"{modern} should not be a legacy peer")
        with patch.object(common, "BACKWARDS_COMPATIBLE", False):
            for version in ((), (5, 1), (7, 0)):
                self.assertFalse(legacy_peer(version))

    def test_set_peer_protocol_version(self):
        proto = Mock()
        with patch("xpra.net.protocol.socket_handler.BACKWARDS_COMPATIBLE", True), \
                patch.object(common, "BACKWARDS_COMPATIBLE", True):
            SocketProtocol.set_peer_protocol_version(proto, (), False)
            self.assertEqual(proto.peer_protocol_version, (5, 1))
            self.assertEqual(proto.packet_type_renames, {})
            SocketProtocol.set_peer_protocol_version(proto, (7, 0), True)
            self.assertEqual(proto.packet_type_renames, get_packet_type_upgrades(True))
        with patch("xpra.net.protocol.socket_handler.BACKWARDS_COMPATIBLE", False), \
                patch.object(common, "BACKWARDS_COMPATIBLE", False):
            # we already use the modern names:
            SocketProtocol.set_peer_protocol_version(proto, (7, 0), True)
            self.assertEqual(proto.packet_type_renames, {})


class LegacyHandlerFallbackTest(unittest.TestCase):

    def dispatch(self, backwards_compatible: bool, packet_type: str):
        dispatcher = PacketDispatcher()
        handler = Mock()
        # registered using the legacy name, as the `DISPLAY_RESIZED` constant does:
        dispatcher.add_packet_handler("desktop_size", handler)
        proto = Mock()
        proto.is_closed.return_value = False
        with patch.object(dispatch, "BACKWARDS_COMPATIBLE", backwards_compatible):
            with silence_error(dispatch):
                dispatcher.dispatch_packet(proto, Packet(packet_type, 1), True)
        return handler, proto

    def test_modern_name_uses_the_legacy_handler(self):
        handler, proto = self.dispatch(True, "display-resized")
        handler.assert_called_once()
        self.assertEqual(handler.call_args[0][1].get_type(), "desktop_size")
        proto.close.assert_not_called()

    def test_no_fallback_when_not_backwards_compatible(self):
        handler, proto = self.dispatch(False, "display-resized")
        handler.assert_not_called()
        proto.close.assert_called_once()

    def test_unknown_packet_is_still_invalid(self):
        handler, proto = self.dispatch(True, "not-a-packet")
        handler.assert_not_called()
        proto.close.assert_called_once()


def main():
    assert packet_type
    unittest.main()


if __name__ == '__main__':
    main()
