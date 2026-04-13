#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import monotonic

from xpra.server.source.source_stats import GlobalPerformanceStatistics, safeint


class TestSafeint(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(safeint(42), 42)
        self.assertEqual(safeint("7"), 7)
        self.assertEqual(safeint(3.9), 3)

    def test_invalid(self):
        self.assertEqual(safeint("bad"), 0)
        self.assertEqual(safeint("bad", 99), 99)


class TestGlobalPerformanceStatistics(unittest.TestCase):

    def setUp(self):
        self.stats = GlobalPerformanceStatistics()

    def test_initial_state(self):
        s = self.stats
        self.assertEqual(s.mmap_size, 0)
        self.assertEqual(s.mmap_bytes_sent, 0)
        self.assertEqual(s.damage_events_count, 0)
        self.assertEqual(s.packet_count, 0)
        self.assertEqual(s.decode_errors, 0)
        self.assertEqual(s.min_client_latency, s.DEFAULT_LATENCY)
        self.assertEqual(s.avg_client_latency, s.DEFAULT_LATENCY)
        self.assertEqual(s.avg_congestion_send_speed, 0)

    def test_reset_clears_deques(self):
        s = self.stats
        now = monotonic()
        s.client_latency.append((1, now, 100, 0.05))
        s.client_ping_latency.append((now, 0.03))
        s.reset()
        self.assertEqual(len(s.client_latency), 0)
        self.assertEqual(len(s.client_ping_latency), 0)

    def test_record_latency(self):
        s = self.stats
        now = monotonic()
        s.record_latency(1, 0, 5000, now - 0.1, 1000, 4096, 80000)
        self.assertEqual(len(s.client_latency), 1)
        self.assertEqual(len(s.frame_total_latency), 1)
        # min_client_latency should be updated
        self.assertLess(s.min_client_latency, s.DEFAULT_LATENCY + 1)

    def test_record_latency_updates_min(self):
        s = self.stats
        now = monotonic()
        s.record_latency(1, 0, 1000, now - 0.2, 100, 512, 180000)
        first_min = s.min_client_latency
        s.record_latency(1, 1, 1000, now - 0.05, 100, 512, 40000)
        # min should stay at or below the first value
        self.assertLessEqual(s.min_client_latency, first_min)

    def test_get_damage_pixels_filters_by_wid(self):
        s = self.stats
        now = monotonic()
        s.damage_packet_qpixels.append((now, 1, 100))
        s.damage_packet_qpixels.append((now, 2, 200))
        s.damage_packet_qpixels.append((now, 1, 150))
        result = s.get_damage_pixels(1)
        self.assertEqual(len(result), 2)
        for _t, px in result:
            self.assertIn(px, (100, 150))

    def test_get_damage_pixels_empty(self):
        self.assertEqual(self.stats.get_damage_pixels(99), ())

    def test_update_averages_empty(self):
        # Should not raise with no data
        self.stats.update_averages()
        self.assertEqual(self.stats.avg_congestion_send_speed, 0)
        self.assertEqual(self.stats.congestion_value, 0)

    def test_update_averages_with_latency(self):
        s = self.stats
        now = monotonic()
        for i in range(5):
            s.client_latency.append((1, now - i, 100, 0.05 + i * 0.01))
            s.client_ping_latency.append((now - i, 0.03 + i * 0.005))
            s.server_ping_latency.append((now - i, 0.02 + i * 0.003))
        s.update_averages()
        self.assertGreater(s.avg_client_latency, 0)
        self.assertGreater(s.avg_client_ping_latency, 0)
        self.assertGreater(s.avg_server_ping_latency, 0)
        self.assertGreater(s.min_client_latency, 0)

    def test_update_averages_frame_total_latency(self):
        s = self.stats
        now = monotonic()
        for i in range(3):
            s.frame_total_latency.append((1, now - i, 1000 * (i + 1), 50 + i * 10))
        s.update_averages()
        self.assertGreater(s.avg_frame_total_latency, 0)

    def test_get_factors_empty(self):
        factors = self.stats.get_factors(1000)
        self.assertIsInstance(factors, list)

    def test_get_factors_with_data(self):
        s = self.stats
        now = monotonic()
        for i in range(5):
            s.client_latency.append((1, now - i, 100, 0.05))
            s.client_ping_latency.append((now - i, 0.03))
            s.server_ping_latency.append((now - i, 0.02))
        s.update_averages()
        factors = s.get_factors(1000)
        self.assertIsInstance(factors, list)
        for metric, info, factor, weight in factors:
            self.assertIsInstance(metric, str)
            self.assertIsInstance(factor, float)
            self.assertGreater(weight, 0)

    def test_get_factors_mmap(self):
        s = self.stats
        s.mmap_size = 4 * 1024 * 1024
        s.mmap_free_size = 1 * 1024 * 1024
        factors = s.get_factors(1000)
        metrics = [f[0] for f in factors]
        self.assertIn("mmap-area", metrics)

    def test_get_factors_congestion(self):
        s = self.stats
        s.congestion_value = 0.5
        factors = s.get_factors(1000)
        metrics = [f[0] for f in factors]
        self.assertIn("congestion", metrics)

    def test_get_connection_info_structure(self):
        info = self.stats.get_connection_info()
        self.assertIn("mmap_bytecount", info)
        self.assertIn("latency", info)
        self.assertIn("server", info)
        self.assertIn("client", info)
        self.assertIn("congestion", info)

    def test_get_info_structure(self):
        info = self.stats.get_info()
        self.assertIn("damage", info)
        self.assertIn("connection", info)
        self.assertIn("encoding", info)
        damage = info["damage"]
        self.assertIn("events", damage)
        self.assertIn("packets_sent", damage)

    def test_get_info_with_decode_data(self):
        s = self.stats
        now = monotonic()
        for i in range(4):
            s.client_decode_time.append((1, now - i, 1000 * (i + 1), 5000 + i * 1000))
            s.quality.append((now - i, 1000, 80 + i))
            s.speed.append((now - i, 1000, 50 + i))
        info = s.get_info()
        einfo = info["encoding"]
        self.assertIn("pixels_decoded_per_second", einfo)
        self.assertIn("quality", einfo)
        self.assertIn("speed", einfo)


if __name__ == "__main__":
    unittest.main()
