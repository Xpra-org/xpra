#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.server.window import perfstats
from xpra.server.window.perfstats import WindowPerformanceStatistics


class PerfStatsTest(unittest.TestCase):

    @patch.object(perfstats, "monotonic", return_value=100.0)
    def test_reset_and_averages(self, _monotonic):
        stats = WindowPerformanceStatistics()
        self.assertEqual(stats.get_client_backlog(), (0, 0))
        stats.damage_in_latency.append((99, 100, 1, 0.02))
        stats.damage_out_latency.append((99, 100, 1, 0.05))
        stats.client_decode_time.extend(((98, 1000, 100), (99, 2000, 200)))
        stats.update_averages()
        self.assertGreater(stats.avg_damage_out_latency, stats.avg_damage_in_latency)
        self.assertGreater(stats.avg_decode_speed, 0)
        self.assertGreaterEqual(stats.max_latency, stats.avg_damage_out_latency)

    @patch.object(perfstats, "monotonic", return_value=100.0)
    def test_backlogs_and_expiry(self, _monotonic):
        stats = WindowPerformanceStatistics()
        stats.damage_ack_pending = {
            1: (99.0, "rgb", 100, 10, {}, 99),
            2: (30.0, "rgb", 200, 20, {}, 30),
            3: (100.0, "rgb", 300, 30, {}, 100),
        }
        self.assertEqual(stats.get_client_backlog(), (1, 100))
        self.assertNotIn(2, stats.damage_ack_pending)
        self.assertEqual(stats.get_acks_pending(), 2)
        self.assertEqual(stats.get_late_acks(0.5), 1)
        stats.encoding_pending = {1: (99, 10, 20), 2: (99, 5, 4)}
        self.assertEqual(stats.get_pixels_encoding_backlog(), (220, 2))

    @patch.object(perfstats, "monotonic", return_value=100.0)
    def test_bitrate_damage_and_factors(self, _monotonic):
        stats = WindowPerformanceStatistics()
        stats.encoding_stats.extend(((99.0, "rgb", 100, 32, 1000, 0.01),
                                     (100.0, "rgb", 100, 32, 2000, 0.02)))
        stats.last_damage_events.extend(((99.5, 0, 0, 10, 20), (90, 0, 0, 99, 99)))
        self.assertEqual(stats.get_bitrate(2), 24000)
        self.assertEqual(stats.get_damage_pixels(1), 200)
        self.assertTrue(stats.get_factors(bandwidth_limit=1000))

    @patch.object(perfstats, "monotonic", return_value=100.0)
    def test_info_and_target_latency(self, _monotonic):
        stats = WindowPerformanceStatistics()
        stats.encoding_totals = {"rgb": [2, 400]}
        stats.encoding_stats.append((99, "rgb", 100, 32, 100, 0.01))
        stats.damage_in_latency.append((99, 100, 0, 0.02))
        info = stats.get_info()
        self.assertEqual(info["total_frames"]["rgb"], 2)
        self.assertIn("ratio_pct", info["rgb"])
        stats.client_decode_time.append((99, 1000, 1000))
        baseline = stats.get_target_client_latency(0.01, 0.02)
        self.assertAlmostEqual(stats.get_target_client_latency(0.01, 0.02, jitter=5) - baseline, 0.005)


if __name__ == "__main__":
    unittest.main()
