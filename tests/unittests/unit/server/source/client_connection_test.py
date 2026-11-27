#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.net.constants import ConnectionMessage
from xpra.server.source import client_connection as cc


class ClientConnectionTest(unittest.TestCase):

    def setUp(self):
        self.protocol = Mock()
        self.disconnect = Mock()
        self.source = cc.ClientConnection(self.protocol, self.disconnect, Mock())

    @patch.object(cc, "MAX_SEND_BACKLOG", 10)
    def test_send_backlog_disconnects_a_client_that_is_not_reading(self):
        for i in range(10):
            self.source.send("test", i)
        self.assertEqual(len(self.source.ordinary_packets), 10)
        self.protocol.idle_add.assert_not_called()

        self.source.send("test", "overflow")
        self.assertEqual(len(self.source.ordinary_packets), 10)
        self.protocol.idle_add.assert_called_once_with(
            self.disconnect, ConnectionMessage.CONNECTION_ERROR, "send queue overflow",
        )

        # The protocol can drain packets while the disconnect is pending.
        self.source.next_packet()
        self.source.send("test", "more")
        self.assertEqual(len(self.source.ordinary_packets), 9)
        self.assertEqual(self.protocol.idle_add.call_count, 1)
        self.assertEqual(self.protocol.source_has_more.call_count, 10)

    @patch.object(cc, "MAX_SEND_BACKLOG", 2)
    def test_normal_send_is_unaffected(self):
        self.source.send("test", 1)
        self.source.send("test", 2)
        self.assertEqual(len(self.source.ordinary_packets), 2)
        self.protocol.idle_add.assert_not_called()
        self.assertEqual(self.protocol.source_has_more.call_count, 2)


if __name__ == "__main__":
    unittest.main()
