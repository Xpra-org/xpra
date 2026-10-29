#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


class ClientConnectionEncodeTeardownTest(unittest.TestCase):

    def test_stop_encode_thread_queues_at_end_handlers_before_marker(self):
        from xpra.server.source.client_connection import ClientConnection

        queued = []

        def record(item):
            queued.append(item)

        cc = ClientConnection(None, lambda: None, lambda *_a: None)
        cc.queue_encode = record
        seen = []

        cc.call_in_encode_thread_at_end(lambda tag: seen.append(tag), "mmap")
        cc.call_in_encode_thread_at_end(lambda tag: seen.append(tag), "cuda")
        cc.stop_encode_thread()

        self.assertEqual(len(queued), 3)
        self.assertIsNone(queued[-1])
        for item in queued[:-1]:
            fn, args = item
            fn(*args)
        self.assertEqual(seen, ["mmap", "cuda"])


if __name__ == "__main__":
    unittest.main()
