#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.server.window import batch_delay_calculator as calc


def batch(**overrides):
    values = dict(delay=20, min_delay=5, max_delay=500, start_delay=20,
                  always=False, locked=False, last_delays=[], last_actual_delays=[],
                  factors=(), last_updated=0)
    values.update(overrides)
    return SimpleNamespace(**values)


def statistics(**overrides):
    values = dict(avg_damage_in_latency=0, avg_decode_speed=0, target_latency=0.05,
                  last_damage_events=[], encoding_stats=[])
    values.update(overrides)
    value = SimpleNamespace(**values)
    value.get_client_backlog = overrides.get("get_client_backlog", lambda: (0, 0))
    return value


def global_statistics(**overrides):
    values = dict(mmap_size=0, congestion_value=0, client_latency=[], recent_client_latency=0,
                  min_client_latency=0.01, avg_client_latency=0.02)
    values.update(overrides)
    return SimpleNamespace(**values)


class BatchDelayCalculatorTest(unittest.TestCase):

    def test_low_limit(self):
        self.assertEqual(calc.get_low_limit(False, (0, 0)), 1024 * 1024)
        self.assertEqual(calc.get_low_limit(False, (320, 200)), 64000)
        self.assertEqual(calc.get_low_limit(True, (320, 200)), 256000)

    @patch.object(calc, "monotonic", return_value=100.0)
    def test_update_batch_delay(self, _monotonic):
        b = batch(last_delays=[(99, 10)], last_actual_delays=[(99, 20)])
        calc.update_batch_delay(b, [("up", {}, 2.0, 1.0)])
        self.assertGreater(b.delay, 20)
        self.assertEqual(b.last_updated, 100.0)
        self.assertEqual(b.factors[0][0], "up")
        previous = b.delay
        calc.update_batch_delay(b, [("ignored", {}, 2.0, 0.0)])
        self.assertEqual(b.delay, previous)
        calc.update_batch_delay(b, [("down", {}, 0.0, 1.0)], min_delay=40)
        self.assertGreaterEqual(b.delay, 40)

    def test_calculate_batch_delay_minimums(self):
        b = batch()
        gs = global_statistics()
        gs.get_factors = lambda _limit: []
        gs.get_damage_pixels = lambda _wid: ()
        stats = statistics()
        stats.get_factors = lambda _bandwidth: []
        stats.get_target_client_latency = lambda *_args, **_kwargs: 0.025
        with patch.object(calc, "queue_inspect", return_value=("queue", {}, 1, 0)), \
                patch.object(calc, "update_batch_delay") as update:
            calc.calculate_batch_delay(1, (100, 100), False, False, False, False,
                                       0, b, gs, stats, 0, 5)
            self.assertEqual(update.call_args.args[2], 40)
            calc.calculate_batch_delay(1, (100, 100), True, True, False, False,
                                       0, b, gs, stats, 0, 5)
            self.assertEqual(update.call_args.args[2], 100)
        self.assertEqual(stats.target_latency, 0.025)

    @patch.object(calc, "monotonic", return_value=100.0)
    def test_target_speed_limits(self, _monotonic):
        b = batch(locked=True)
        stats = statistics(get_client_backlog=lambda: (2, 4 * 1024 * 1024))
        gs = global_statistics(congestion_value=0.05)
        info, speed, max_speed = calc.get_target_speed((1024, 1024), b, gs, stats,
                                                       bandwidth_limit=1_000_000,
                                                       min_speed=10, speed_data=())
        self.assertGreaterEqual(speed, 10)
        self.assertLessEqual(speed, max_speed)
        self.assertEqual(info["min-speed"], 10)
        self.assertLess(info["limits"]["congestion"], 100)

    @patch.object(calc, "monotonic", return_value=100.0)
    def test_target_quality_bounds(self, _monotonic):
        stats = statistics(get_client_backlog=lambda: (0, 0))
        info, quality = calc.get_target_quality((800, 600), batch(), global_statistics(), stats,
                                                bandwidth_limit=0, min_quality=25, min_speed=0)
        self.assertGreaterEqual(quality, 25)
        self.assertLessEqual(quality, 100)
        self.assertEqual(info["min-quality"], 25)
        congested = global_statistics(congestion_value=1)
        _, lower_quality = calc.get_target_quality((800, 600), batch(), congested, stats,
                                                   bandwidth_limit=0, min_quality=25, min_speed=50)
        self.assertEqual(lower_quality, 25)


if __name__ == "__main__":
    unittest.main()
