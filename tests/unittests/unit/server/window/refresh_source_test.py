#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.window import compress
from xpra.server.window.compress import WindowSource
from xpra.server.window.refresh import RefreshController
from xpra.net.common import Packet
from xpra.net.packet_type import WINDOW_DRAW
from xpra.util.objects import typedict
from xpra.util.rectangle import rectangle
from unit.server.window.refresh_test_util import FakeClock, FakeScheduler


class RefreshDeadlineTest(unittest.TestCase):

    def test_partial_updates_have_a_bounded_refresh_deadline(self):
        source = object.__new__(WindowSource)
        source.encoding = "auto"
        source.image_depth = 24
        source.refresh_quality = 100
        source.window_dimensions = 100, 100
        source.base_auto_refresh_delay = 200
        source.min_auto_refresh_delay = 50
        source.batch_config = SimpleNamespace(delay=0)
        source.global_statistics = SimpleNamespace(congestion_value=0)
        clock = FakeClock()
        source.refresh_controller = RefreshController(
            FakeScheduler(), clock, can_refresh=source.can_refresh, on_refresh=source.timer_full_refresh,
        )
        region = rectangle(0, 0, 50, 50)
        with patch.object(compress, "monotonic", clock):
            # Keep repainting a partial region while the UI timer is pending.
            # The initial 200ms refresh delay permits at most one second of postponement.
            for i in range(100):
                clock.now = 100 + i/100
                source.do_schedule_auto_refresh("jpeg", region, {"quality": 50}, typedict())
        self.assertEqual(source.refresh_controller.event_time, 100)
        self.assertLessEqual(source.refresh_controller.target_time, 101)


class RefreshSourceTest(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.scheduler = FakeScheduler()
        for p in (patch.object(compress, "GLib", self.scheduler), patch.object(compress, "monotonic", self.clock)):
            self.enterContext(p)

    def make_source(self, source_type=WindowSource):
        source = object.__new__(source_type)
        WindowSource.init_vars(source)
        source.encoding = "auto"
        source.image_depth = 24
        source.window_dimensions = 100, 100
        source.base_auto_refresh_delay = 200
        source.min_auto_refresh_delay = 50
        source.auto_refresh_delay = 200
        source.auto_refresh_encodings = ("png",)
        source._damage_cancelled = 0
        source._current_quality = 50
        source.batch_config = SimpleNamespace(delay=0)
        source.global_statistics = SimpleNamespace(congestion_value=0)
        source.window = Mock()
        source.window.is_managed.return_value = True
        source.wid = 1
        source.av_sync_timer = 0
        source.encode_queue = []
        source.statistics = SimpleNamespace(encoding_pending={})
        source.do_send_regions = Mock()
        source.send_delayed_regions = Mock()
        self.addCleanup(source.refresh_controller.cancel)
        return source

    def make_video_source(self, video_rect):
        from xpra.server.window.video_compress import WindowVideoSource
        source = self.make_source(WindowVideoSource)
        source.video_subregion = SimpleNamespace(
            rectangle=video_rect, add_video_refresh=Mock(), remove_refresh_region=Mock(),
        )
        source.free_scroll_data = Mock()
        source.last_scroll_time = 100
        return source

    def test_timer_sends_pending_regions_with_refresh_options(self):
        source = self.make_source()
        region = rectangle(0, 0, 50, 50)
        source.do_schedule_auto_refresh("jpeg", region, {"quality": 50}, typedict())
        self.clock.advance(0.1)
        self.assertFalse(self.scheduler.fire(source.refresh_controller.timer))
        source.do_send_regions.assert_called_once()
        args, kwargs = source.do_send_regions.call_args
        self.assertEqual(args[:3], (self.clock.now, [region], "png"))
        self.assertEqual(args[3], source.get_refresh_options())
        self.assertEqual(kwargs, {"exclude_region": None, "get_best_encoding": source.get_refresh_encoding})
        self.assertEqual(source.refresh_controller.regions, [])
        self.assertEqual(source.refresh_controller.timer, 0)

    def test_timer_rechecks_window_management(self):
        source = self.make_source()
        source.do_schedule_auto_refresh("jpeg", rectangle(0, 0, 50, 50), {}, typedict())
        source.window.is_managed.return_value = False
        self.clock.advance(1)
        self.scheduler.fire(source.refresh_controller.timer)
        source.do_send_regions.assert_not_called()
        self.assertEqual(source.refresh_controller.event_time, 0)

    def test_scaled_refresh_does_not_schedule_another_refresh(self):
        for video in (False, True):
            with self.subTest(video=video):
                source = self.make_video_source(rectangle(0, 0, 50, 100)) if video else self.make_source()
                region = rectangle(0, 0, 100, 100)
                client_options = {"quality": 100, "scaled_size": (20, 20)}
                packet = Packet(WINDOW_DRAW, source.wid, 0, 0, 100, 100, "webp", b"data", 1, 0, client_options)
                source.schedule_auto_refresh(packet, typedict())
                self.assertTrue(source.refresh_controller.regions)
                if video:
                    source.video_subregion.add_video_refresh.reset_mock()
                timer = source.refresh_controller.timer
                source.schedule_auto_refresh(packet, typedict(source.get_refresh_options()))
                self.assertEqual(source.refresh_controller.regions, [])
                self.assertEqual(source.refresh_controller.timer, 0)
                self.assertIn(timer, self.scheduler.cancelled)
                self.assertFalse(self.scheduler.tasks)
                if video:
                    source.video_subregion.add_video_refresh.assert_not_called()
                    source.video_subregion.remove_refresh_region.assert_called_once_with(region)

    def test_scaled_refresh_keeps_its_flag_when_delayed_video_frames_are_flushed(self):
        from xpra.server.window import video_compress
        source = self.make_video_source(None)
        source.client_render_size = 20, 20
        source.pixel_format = "RGB"
        source.video_helper = Mock()
        source.width_mask = source.height_mask = 0xffff
        source.start_video_frame = 0
        source.video_stream_file = None
        source.b_frame_flush_timer = 0
        source.scroll_data = None
        source.global_statistics.packet_count = 0
        source.statistics.packet_count = 0
        source.statistics.encoding_totals = {}
        source.may_use_scrolling = Mock(return_value=False)
        source.check_pipeline = Mock(return_value=True)
        source.get_video_encoder_options = Mock(return_value={})
        source.cancel_video_encoder_timer = Mock()
        source.schedule_video_encoder_timer = Mock()
        source.call_in_encode_thread = Mock(side_effect=lambda callback: callback())
        source.queue_damage_packet = Mock(
            side_effect=lambda packet, _damage_time, _process_time, options: source.schedule_auto_refresh(packet, options),
        )
        image = Mock()
        image.get_geometry.return_value = 0, 0, 100, 100
        image.get_pixel_format.return_value = "RGB"
        source.csc_image = Mock(return_value=(Mock(), image, "RGB", 20, 20))
        encoder = source._video_encoder = Mock()
        encoder.is_closed.return_value = False
        encoder.get_type.return_value = "test"
        encoder.get_encoding.return_value = "h264"
        encoder.get_width.return_value = encoder.get_height.return_value = 100
        encoder.compress_image.return_value = b"data", {"quality": 100, "frame": 1, "delayed": 2}
        encoder.flush.side_effect = [
            (b"frame1", {"quality": 100, "delayed": 1}),
            (b"frame2", {"quality": 100, "delayed": 0}),
        ]
        with patch.object(video_compress, "GLib", self.scheduler):
            source.do_video_encode("h264", image, typedict(source.get_refresh_options()))
            for _ in range(2):
                self.scheduler.fire(source.b_frame_flush_timer)
                self.assertEqual(source.refresh_controller.regions, [])
                self.assertEqual(source.refresh_controller.timer, 0)
        self.assertEqual(source.queue_damage_packet.call_count, 2)
        self.assertFalse(self.scheduler.tasks)
        source.video_subregion.add_video_refresh.assert_not_called()

    def test_lossless_completion_does_not_read_cleaned_up_settings(self):
        source = self.make_source()
        region = rectangle(0, 0, 50, 50)
        source.do_schedule_auto_refresh("jpeg", region, {}, typedict())
        source.batch_config = None
        source.global_statistics = None
        source.do_schedule_auto_refresh("rgb24", region, {}, typedict())
        self.assertEqual(source.refresh_controller.regions, [])
        self.assertEqual(source.refresh_controller.timer, 0)

    def test_cleaned_up_dimensions_cancel_before_reading_statistics(self):
        source = self.make_source()
        region = rectangle(0, 0, 50, 50)
        source.do_schedule_auto_refresh("jpeg", region, {}, typedict())
        source.window_dimensions = 0, 0
        source.batch_config = None
        source.global_statistics = None
        source.do_schedule_auto_refresh("jpeg", region, {}, typedict())
        self.assertEqual(source.refresh_controller.timer, 0)

    def test_stream_mode_does_not_schedule_refresh(self):
        source = self.make_source()
        source.encoding = "stream"
        source.do_schedule_auto_refresh("jpeg", rectangle(0, 0, 50, 50), {}, typedict())
        self.assertEqual(source.refresh_controller.regions, [])
        self.assertFalse(self.scheduler.scheduled)

    def test_new_damage_postpones_only_a_pending_lossy_refresh(self):
        source = self.make_source()
        region = rectangle(0, 0, 50, 50)
        source.do_schedule_auto_refresh("jpeg", region, {}, typedict())
        source._damage_delayed = compress.DelayedRegions(self.clock.now, "jpeg", {}, [region])
        source.soft_expired = 1
        self.clock.advance(0.04)
        source.do_damage(100, 100, 0, 0, 10, 10, {})
        self.assertAlmostEqual(source.refresh_controller.target_time, 100.09)
        self.clock.advance(0.02)
        source.do_damage(100, 100, 0, 0, 10, 10, {"quality": 100})
        self.assertAlmostEqual(source.refresh_controller.target_time, 100.09)
        self.assertEqual(len(self.scheduler.scheduled), 1)

    def test_congestion_postpones_the_controller_deadline(self):
        source = self.make_source()
        source.global_statistics.bytes_sent = []
        source.record_congestion_event = Mock()
        source.do_schedule_auto_refresh("jpeg", rectangle(0, 0, 50, 50), {}, typedict())
        source.networksend_congestion_event("test", 50, 1000000)
        self.assertEqual(source.refresh_controller.target_time, 102)
        source.record_congestion_event.assert_called_once_with("test", 50, 1000000)

    def test_cancelling_damage_clears_pending_refresh_and_removes_timer(self):
        source = self.make_source()
        source.do_schedule_auto_refresh("jpeg", rectangle(0, 0, 50, 50), {}, typedict())
        timer = source.refresh_controller.timer
        source.cancel_damage()
        self.assertEqual(source.refresh_controller.regions, [])
        self.assertEqual(source.refresh_controller.timer, 0)
        self.assertEqual(source.refresh_controller.event_time, 0)
        self.assertEqual(source.refresh_controller.target_time, 0)
        self.assertEqual(self.scheduler.cancelled, [timer])
        source.window.acknowledge_changes.assert_not_called()

    def test_full_quality_refresh_detaches_pending_regions(self):
        source = self.make_source()
        source.do_schedule_auto_refresh("jpeg", rectangle(0, 0, 50, 50), {}, typedict())
        options = {"custom": True}
        source.full_quality_refresh(options)
        self.assertEqual(source.refresh_controller.regions, [])
        source.send_delayed_regions.assert_called_once()
        damage = source.send_delayed_regions.call_args.args[0]
        self.assertEqual(damage.regions, [rectangle(0, 0, 100, 100)])
        self.assertTrue(damage.options["auto_refresh"])
        self.assertTrue(damage.options["custom"])
        self.assertEqual(options, {"custom": True})

    def test_video_updates_split_regions_and_lossless_coverage(self):
        source = self.make_video_source(rectangle(0, 0, 50, 100))
        region = rectangle(25, 0, 50, 50)
        source.do_schedule_auto_refresh("jpeg", region, {}, typedict())
        self.assertEqual(source.refresh_controller.regions, [rectangle(50, 0, 25, 50)])
        source.video_subregion.add_video_refresh.assert_called_once_with(rectangle(25, 0, 25, 50))
        source.do_schedule_auto_refresh("rgb24", region, {}, typedict())
        source.video_subregion.remove_refresh_region.assert_called_once_with(region)
        self.assertEqual(source.refresh_controller.timer, 0)
        self.assertEqual(source.refresh_controller.regions, [])

    def test_whole_video_window_uses_only_its_separate_refresh(self):
        source = self.make_video_source(rectangle(0, 0, 100, 100))
        region = rectangle(0, 0, 50, 50)
        source.do_schedule_auto_refresh("jpeg", region, {}, typedict())
        self.assertEqual(source.refresh_controller.regions, [])
        self.assertFalse(self.scheduler.scheduled)
        source.video_subregion.add_video_refresh.assert_called_once_with(region)

    def test_video_timer_keeps_its_cleanup_and_current_exclusion(self):
        source = self.make_video_source(rectangle(0, 0, 50, 100))
        source.do_schedule_auto_refresh("jpeg", rectangle(50, 0, 50, 50), {}, typedict())
        source.video_subregion.rectangle = rectangle(0, 0, 25, 100)
        self.clock.advance(1)
        self.scheduler.fire(source.refresh_controller.timer)
        source.free_scroll_data.assert_called_once_with()
        self.assertEqual(source.last_scroll_time, 0)
        self.assertEqual(source.do_send_regions.call_args.kwargs["exclude_region"], source.video_subregion.rectangle)

    def test_scroll_moves_pending_regions_without_rescheduling(self):
        source = self.make_video_source(None)
        region = rectangle(0, 0, 10, 10)
        source.do_schedule_auto_refresh("jpeg", region, {}, typedict())
        timer = source.refresh_controller.timer
        target = source.refresh_controller.target_time
        source.do_schedule_auto_refresh("scroll", rectangle(0, 0, 50, 10),
                                        {"scroll": [(0, 0, 10, 10, 20, 0)]}, typedict())
        self.assertEqual(source.refresh_controller.regions, [region, rectangle(20, 0, 10, 10)])
        self.assertEqual(source.refresh_controller.timer, timer)
        self.assertEqual(source.refresh_controller.target_time, target)
        self.assertEqual(len(self.scheduler.scheduled), 1)


if __name__ == '__main__':
    unittest.main()
