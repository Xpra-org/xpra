#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.source.encoding import EncodingsConnection
from xpra.server.source.source_stats import GlobalPerformanceStatistics


class EncodingConnectionTest(unittest.TestCase):

    @staticmethod
    def connection(conn):
        source = EncodingsConnection()
        source.init_state()
        source.statistics = GlobalPerformanceStatistics()
        source.protocol = SimpleNamespace(is_closed=lambda: False, _conn=conn)
        source.window_sources = {}
        source.get_focus = lambda: 0
        return source

    def test_quic_snapshot_reaches_batch_statistics(self):
        control = Mock()
        control.get_info.return_value = {
            "pending-new-bytes": 30000, "pending-retransmit-bytes": 20000, "pending-bytes": 50000,
            "recent": {"status": "active", "acked-bitrate": 800000},
        }
        source = self.connection(SimpleNamespace(output_bytecount=10000000, congestion_control=control))
        source.recalculate_delays()
        control.get_info.assert_called_once_with()
        sample = source.statistics.transport_queue[-1]
        self.assertEqual(sample.queued_bytes, 50000)
        self.assertEqual(sample.queued_time, 0.5)
        self.assertEqual([f[0] for f in source.statistics.get_factors(1000)], ["transport-queue"])
        control.get_info.return_value = {"pending-bytes": 0, "recent": {"status": "idle"}}
        source.recalculate_delays()
        sample = source.statistics.transport_queue[-1]
        self.assertEqual(sample.queued_bytes, 0)
        self.assertEqual(sample.queued_time, 0.0)

    def test_tcp_socket_query_uses_shared_recorder(self):
        sock = object()
        conn = SimpleNamespace(output_bytecount=0, socktype_wrapped="tcp", get_raw_socket=lambda: sock)
        source = self.connection(conn)
        with patch("xpra.platform.netdev_query.get_socket_tcp_info",
                   return_value={"notsent_bytes": 50000, "delivery_rate": 100000}) as query:
            source.recalculate_delays()
        query.assert_called_once_with(sock)
        sample = source.statistics.transport_queue[-1]
        self.assertEqual(sample.queued_bytes, 50000)
        self.assertEqual(sample.queued_time, 0.5)

    def test_connections_without_queue_metrics(self):
        source = self.connection(SimpleNamespace(output_bytecount=1000))
        source.recalculate_delays()
        self.assertFalse(source.statistics.transport_queue)


if __name__ == "__main__":
    unittest.main()
