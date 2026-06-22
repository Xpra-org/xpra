#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the client `BandwidthClient` subsystem to the
server `BandwidthManager` subsystem (+ `BandwidthConnection` source).

A single packet ("bandwidth-limit") flows client -> server.
"""

import unittest

from xpra.util.objects import AdHocStruct

from unit.loopback_util import LoopbackTest


def _client_opts():
    opts = AdHocStruct()
    opts.bandwidth_limit = "0"
    opts.bandwidth_detection = False
    return opts


def _server_opts():
    opts = AdHocStruct()
    # a non-zero server limit avoids a socket-speed lookup on the stub protocol:
    opts.bandwidth_limit = "1Gbps"
    opts.bandwidth_detection = False
    return opts


class BandwidthLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.bandwidth import BandwidthClient
        from xpra.server.subsystem.bandwidth import BandwidthManager
        from xpra.server.source.bandwidth import BandwidthConnection
        return self.connect(BandwidthClient, BandwidthManager, BandwidthConnection,
                            client_opts=_client_opts(), server_opts=_server_opts(),
                            caps={})

    def test_client_bandwidth_limit_applied_to_source(self):
        client, _server, source = self._connect()
        # the source starts with no client-imposed limit:
        self.assertEqual(source.bandwidth_limit, 0)

        limit = 5 * 1024 * 1024  # 5 MiB/s, within [MIN, MAX]
        client.bandwidth_limit = limit
        client.send_bandwidth_limit()

        # the packet crossed the wire:
        self.assertIn(("bandwidth-limit", limit), [tuple(p) for p in self.c2s])
        # and the server applied it to the per-client source:
        self.assertEqual(source.bandwidth_limit, limit)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
