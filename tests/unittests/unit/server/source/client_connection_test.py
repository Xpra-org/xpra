#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.server.source import client_connection as cc


class FakeProtocol:
    def __init__(self):
        self.more = 0

    def idle_add(self, fn, *args):
        # run the scheduled call inline:
        fn(*args)

    def source_has_more(self):
        self.more += 1


class ClientConnectionTest(unittest.TestCase):

    def make_source(self):
        src = cc.ClientConnection.__new__(cc.ClientConnection)
        src.ordinary_packets = []
        src.send_backlog_exceeded = False
        src.counter = 1
        src.protocol = FakeProtocol()
        src.disconnected = []
        src.disconnect = lambda *args: src.disconnected.append(args)
        return src

    def test_send_backlog_disconnects_a_client_that_is_not_reading(self):
        src = self.make_source()
        with patch.object(cc, "MAX_SEND_BACKLOG", 10):
            # fill the queue up to the limit:
            for i in range(10):
                src.send("test", i)
            self.assertEqual(len(src.ordinary_packets), 10)
            self.assertEqual(src.disconnected, [])
            # the next packet exceeds the cap: it must be dropped and the client disconnected:
            src.send("test", "overflow")
            self.assertEqual(len(src.ordinary_packets), 10, "packet past the cap must not be queued")
            self.assertEqual(len(src.disconnected), 1, "the client must be disconnected")
            self.assertTrue(src.send_backlog_exceeded)
            # further sends stay dropped and must not schedule another disconnect:
            src.send("test", "more")
            self.assertEqual(len(src.ordinary_packets), 10)
            self.assertEqual(len(src.disconnected), 1, "disconnect must only be triggered once")

    def test_normal_send_is_unaffected(self):
        src = self.make_source()
        src.send("test", 1)
        src.send("test", 2)
        self.assertEqual(len(src.ordinary_packets), 2)
        self.assertEqual(src.disconnected, [])
        self.assertEqual(src.protocol.more, 2)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
