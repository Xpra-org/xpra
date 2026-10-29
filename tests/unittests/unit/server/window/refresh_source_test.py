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
from xpra.net.common import Packet
from xpra.net.packet_type import WINDOW_DRAW
from xpra.util.objects import typedict
from xpra.util.rectangle import rectangle


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
        source.refresh_regions = []
        source.refresh_timer = 0
        source.refresh_event_time = 0
        source.refresh_target_time = 0
        region = rectangle(0, 0, 50, 50)
        with patch.object(compress.GLib, "timeout_add", return_value=1), patch.object(compress, "monotonic") as clock:
            # Keep repainting a partial region while the UI timer is pending.
            # The initial 200ms refresh delay permits at most one second of postponement.
            for i in range(100):
                clock.return_value = 100 + i/100
                source.do_schedule_auto_refresh("jpeg", region, {"quality": 50}, typedict())
        self.assertEqual(source.refresh_event_time, 100)
        self.assertLessEqual(source.refresh_target_time, 101)


class FakeScheduler:
    def __init__(self):
        self.tasks = {}
        self.cancelled = []
        self.next_id = 1

    def timeout_add(self, _delay, callback, *args):
        tid = self.next_id
        self.next_id += 1
        self.tasks[tid] = callback, args
        return tid

    def source_remove(self, tid):
        self.cancelled.append(tid)
        self.tasks.pop(tid, None)

    def fire(self, tid):
        callback, args = self.tasks.pop(tid)
        return callback(*args)


class RefreshSourceTest(unittest.TestCase):

    def setUp(self):
        self.scheduler = FakeScheduler()
        self.enterContext(patch.object(compress, "GLib", self.scheduler))
        self.enterContext(patch.object(compress, "monotonic", return_value=100))

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
        source.refresh_quality = 100
        source._damage_cancelled = 0
        source.batch_config = SimpleNamespace(delay=0)
        source.global_statistics = SimpleNamespace(congestion_value=0)
        source.window = Mock()
        source.window.is_managed.return_value = True
        source.wid = 1
        source.statistics = SimpleNamespace(encoding_pending={})
        self.addCleanup(source.cancel_refresh_timer)
        return source

    def make_video_source(self, video_rect):
        from xpra.server.window.video_compress import WindowVideoSource
        source = self.make_source(WindowVideoSource)
        source.video_subregion = SimpleNamespace(
            rectangle=video_rect, add_video_refresh=Mock(), remove_refresh_region=Mock(),
        )
        return source

    def test_scaled_refresh_does_not_schedule_another_refresh(self):
        for video in (False, True):
            with self.subTest(video=video):
                source = self.make_video_source(rectangle(0, 0, 50, 100)) if video else self.make_source()
                region = rectangle(0, 0, 100, 100)
                client_options = {"quality": 100, "scaled_size": (20, 20)}
                packet = Packet(WINDOW_DRAW, source.wid, 0, 0, 100, 100, "webp", b"data", 1, 0, client_options)
                source.schedule_auto_refresh(packet, typedict())
                self.assertTrue(source.refresh_regions)
                if video:
                    source.video_subregion.add_video_refresh.reset_mock()
                timer = source.refresh_timer
                source.schedule_auto_refresh(packet, typedict(source.get_refresh_options()))
                self.assertEqual(source.refresh_regions, [])
                self.assertEqual(source.refresh_timer, 0)
                self.assertIn(timer, self.scheduler.cancelled)
                self.assertFalse(self.scheduler.tasks)
                if video:
                    source.video_subregion.add_video_refresh.assert_not_called()
                    source.video_subregion.remove_refresh_region.assert_called_once_with(region)

    def test_downscaled_webp_refreshes_and_resets_scroll_data(self):
        try:
            from xpra.codecs.webp.encoder import encode
        except ImportError:
            self.skipTest("WebP encoder is not available")
        from xpra.codecs.checks import make_test_image

        source = self.make_video_source(None)
        source.scroll_data = scroll_data = Mock()
        source.global_statistics.packet_count = 0
        source.statistics.packet_count = 0
        source.statistics.encoding_totals = {}
        options = typedict({"quality": 100, "scaled-width": 20, "scaled-height": 20})
        image = make_test_image("BGRX", 100, 100)
        coding, data, client_options, w, h, stride, _bpp = encode("webp", image, options)
        packet = source.make_draw_packet(0, 0, w, h, coding, data, stride, client_options, options)
        source.schedule_auto_refresh(packet, options)

        self.assertEqual(packet[4:6], (100, 100))
        self.assertEqual(client_options["quality"], 100)
        self.assertEqual(source.refresh_regions, [rectangle(0, 0, 100, 100)])
        self.assertTrue(source.refresh_timer)
        self.assertIsNone(source.scroll_data)
        scroll_data.free.assert_called_once_with()
        scroll_data.invalidate.assert_not_called()

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
                self.assertEqual(source.refresh_regions, [])
                self.assertEqual(source.refresh_timer, 0)
        self.assertEqual(source.queue_damage_packet.call_count, 2)
        self.assertFalse(self.scheduler.tasks)
        source.video_subregion.add_video_refresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
