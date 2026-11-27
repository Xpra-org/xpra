#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.server.source import client_connection
from xpra.util import ConnectionMessage


class ClientConnectionTest(unittest.TestCase):

    def setUp(self):
        self.protocol = Mock()
        self.disconnect = Mock()
        self.source = client_connection.ClientConnection(
            self.protocol, self.disconnect, "test", None, "", (), False, 0, False,
        )

    def test_send_backlog_disconnects_once(self):
        with patch.object(client_connection, "MAX_SEND_BACKLOG", 10):
            for i in range(10):
                self.source.send("test", i)
            self.assertEqual(len(self.source.ordinary_packets), 10)
            self.protocol.idle_add.assert_not_called()

            self.source.send("test", "overflow")
            self.assertEqual(len(self.source.ordinary_packets), 10)
            self.protocol.idle_add.assert_called_once_with(
                self.disconnect, ConnectionMessage.CONNECTION_ERROR, "send queue overflow",
            )

            # Keep dropping packets while the scheduled disconnect is pending.
            self.source.next_packet()
            self.source.send("test", "after overflow")
            self.assertEqual(len(self.source.ordinary_packets), 9)
            self.assertEqual(self.protocol.idle_add.call_count, 1)
            self.assertEqual(self.protocol.source_has_more.call_count, 10)

    def test_normal_send_preserves_packet_options(self):
        fail_cb = Mock()
        self.source.send("test", 1, synchronous=False, will_have_more=False, fail_cb=fail_cb)
        self.source.send("test", 2)
        self.assertEqual(self.source.next_packet(), (("test", 1), None, None, fail_cb, False, True, False))
        self.assertEqual(self.source.next_packet(), (("test", 2), None, None, None, True, False, False))
        self.assertEqual(self.protocol.source_has_more.call_count, 2)
        self.protocol.idle_add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
