#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from dataclasses import replace

from xpra.server.window.refresh import RefreshController, RefreshSettings
from xpra.util.rectangle import rectangle
from unit.server.window.refresh_test_util import FakeClock, FakeScheduler


class RefreshControllerTest(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.scheduler = FakeScheduler()
        self.allowed = True
        self.flushed = []
        self.controller = RefreshController(
            self.scheduler, self.clock, can_refresh=lambda: self.allowed,
            on_refresh=lambda: self.flushed.append(self.controller.take_regions()),
        )
        self.settings = RefreshSettings(100, 100, 200)
        self.region = rectangle(0, 0, 50, 50)

    def update(self, region=None, settings=None, **kwargs):
        return self.controller.update(region or self.region, settings or self.settings, lossy=True, **kwargs)

    def test_first_partial_update_schedules_refresh(self):
        self.update()
        self.assertEqual(self.controller.regions, [self.region])
        self.assertEqual(self.controller.event_time, 100)
        self.assertAlmostEqual(self.controller.target_time, 100.05)
        self.assertEqual(self.scheduler.scheduled, [(1, 50)])
        self.assertEqual(self.controller.last_message[0], 100)

    def test_lossless_coverage_subtracts_regions_and_cancels(self):
        self.update()
        timer = self.controller.timer
        self.controller.update(rectangle(0, 0, 25, 50), lossy=False)
        self.assertEqual(sum(r.width*r.height for r in self.controller.regions), 1250)
        self.assertEqual(self.controller.timer, timer)
        self.controller.update(rectangle(25, 0, 25, 50), lossy=False)
        self.assertEqual(self.controller.regions, [])
        self.assertEqual(self.controller.timer, 0)
        self.assertEqual(self.controller.event_time, 0)
        self.assertEqual(self.controller.target_time, 0)
        self.assertEqual(self.scheduler.cancelled, [timer])

    def test_auto_refresh_packet_does_not_reschedule_itself(self):
        self.update()
        self.controller.update(self.region, lossy=True, auto_refresh=True)
        self.assertEqual(self.controller.regions, [])
        self.assertFalse(self.scheduler.tasks)
        self.assertEqual(len(self.scheduler.scheduled), 1)
        self.controller.update(self.region, lossy=False)
        self.assertEqual(self.controller.last_message[1], "lossless - nothing to do")

    def test_overlapping_updates_track_union_without_duplicate_pixels(self):
        self.update()
        self.update(rectangle(25, 25, 50, 50))
        self.assertEqual(sum(r.width*r.height for r in self.controller.regions), 4375)
        self.assertEqual(len(self.scheduler.scheduled), 1)

    def test_significant_added_area_extends_the_target(self):
        self.update(rectangle(0, 0, 10, 10))
        self.clock.advance(0.01)
        self.update(rectangle(30, 30, 50, 50))
        self.assertAlmostEqual(self.controller.target_time, 100.062)
        self.assertIn("re-scheduling", self.controller.last_message[1])

    def test_repeated_updates_have_a_bounded_target(self):
        for i in range(100):
            self.clock.now = 100 + i/100
            self.update()
        self.assertLessEqual(self.controller.target_time, 101)
        self.assertEqual(self.controller.event_time, 100)
        self.assertEqual(len(self.scheduler.scheduled), 1)

    def test_full_window_restarts_the_timer(self):
        self.update()
        old_timer = self.controller.timer
        self.clock.advance(0.01)
        self.update(rectangle(0, 0, 100, 100))
        self.assertEqual(self.scheduler.cancelled, [old_timer])
        self.assertNotEqual(self.controller.timer, old_timer)
        self.assertAlmostEqual(self.controller.target_time, 100.21)
        self.assertEqual(self.controller.event_time, self.clock.now)
        self.assertEqual(sum(r.width*r.height for r in self.controller.regions), 10000)

    def test_empty_window_cancels_pending_timer(self):
        self.update()
        self.update(settings=replace(self.settings, width=0))
        self.assertEqual(self.controller.timer, 0)
        self.assertFalse(self.scheduler.tasks)
        self.assertEqual(self.controller.regions, [self.region])

    def test_exclusion_accounts_for_only_the_nonvideo_pixels(self):
        exclude = rectangle(0, 0, 50, 100)
        self.controller = RefreshController(
            self.scheduler, self.clock, can_refresh=lambda: self.allowed,
            on_refresh=lambda: self.flushed.append(self.controller.take_regions()),
            add_region=lambda region: sum(self.controller.add_region(r) for r in region.subtract_rect(exclude)),
        )
        self.update(rectangle(25, 0, 50, 50), exclude=exclude)
        self.assertEqual(self.controller.regions, [rectangle(50, 0, 25, 50)])
        self.assertEqual(self.scheduler.scheduled, [(1, 50)])
        self.controller.cancel()
        self.controller.clear_regions()
        self.update(rectangle(0, 0, 50, 50), exclude=exclude)
        self.assertEqual(self.controller.timer, 0)
        self.assertEqual(self.controller.regions, [])
        self.assertEqual(self.controller.last_message[1], "nothing to refresh")
        exclude = rectangle(0, 0, 100, 100)
        self.update(exclude, exclude=exclude)
        self.assertEqual(self.controller.timer, 0)

    def test_callback_reschedules_to_the_moved_target(self):
        settings = replace(self.settings, base_delay=1000)
        self.update(settings=settings)
        timer = self.controller.timer
        self.clock.advance(0.04)
        self.update(settings=settings)
        self.clock.advance(0.01)
        self.assertFalse(self.scheduler.fire(timer))
        self.assertEqual(self.flushed, [])
        self.assertNotEqual(self.controller.timer, timer)
        self.assertAlmostEqual(self.scheduler.scheduled[-1][1], 240, delta=1)
        self.clock.now = self.controller.target_time-0.049
        self.assertFalse(self.scheduler.fire(self.controller.timer))
        self.assertEqual(self.flushed, [(100, [self.region])])
        self.assertEqual(self.controller.timer, 0)
        self.assertEqual(self.controller.regions, [])

    def test_callback_rechecks_window_and_event_state(self):
        self.update()
        self.allowed = False
        self.assertFalse(self.scheduler.fire(self.controller.timer))
        self.assertEqual(self.flushed, [])
        self.assertEqual(self.controller.event_time, 0)
        self.assertEqual(self.controller.timer, 0)
        self.allowed = True
        self.update()
        self.controller.event_time = 0
        self.assertFalse(self.scheduler.fire(self.controller.timer))
        self.assertEqual(self.flushed, [])

    def test_cancel_and_take_regions(self):
        self.update()
        regions = self.controller.regions
        event_time, taken = self.controller.take_regions()
        self.assertIs(taken, regions)
        self.assertEqual(event_time, 100)
        self.assertEqual(self.controller.regions, [])
        self.assertEqual(self.controller.event_time, 0)
        self.controller.cancel()
        self.controller.cancel()
        self.assertEqual(self.scheduler.cancelled, [1])

    def test_damage_and_congestion_postponement(self):
        self.controller.postpone(2, self.clock.now)
        self.assertEqual(self.controller.target_time, 0)
        self.controller.postpone_for_damage(self.settings, self.clock.now)
        self.update()
        self.controller.postpone_for_damage(replace(self.settings, congestion=3), self.clock.now)
        self.assertAlmostEqual(self.controller.target_time, 100.2)
        self.controller.postpone(2, self.clock.now)
        self.assertEqual(self.controller.target_time, 102)
        self.controller.postpone(1, self.clock.now)
        self.assertEqual(self.controller.target_time, 102)
        self.assertEqual(len(self.scheduler.scheduled), 1)
        self.controller.regions = []
        self.controller.postpone_for_damage(self.settings, self.clock.now)
        self.controller.regions = [rectangle(0, 0, 0, 10)]
        self.controller.postpone_for_damage(self.settings, self.clock.now)
        self.assertEqual(self.controller.target_time, 102)


if __name__ == '__main__':
    unittest.main()
