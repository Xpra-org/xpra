#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from unittest.mock import Mock, patch

from xpra.codecs.constants import CSCSpec, VideoSpec
from xpra.server.window import video_compress
from xpra.server.window.video_compress import WindowVideoSource
from xpra.util.objects import typedict
from unit.server.window.refresh_test_util import FakeScheduler


class VideoEncoderTimeoutTest(unittest.TestCase):

    def setUp(self) -> None:
        self.scheduler = FakeScheduler()
        self.enterContext(patch.object(video_compress, "GLib", self.scheduler))
        self.enterContext(patch.object(video_compress, "VIDEO_TIMEOUT", 10))
        self.enterContext(patch.object(video_compress, "VIDEO_GPU_TIMEOUT", 2))
        self.encode_queue = []
        self.source = source = WindowVideoSource.__new__(WindowVideoSource)
        source.init_vars()
        source.wid = 1
        source.video_stream_file = None
        source.call_in_encode_thread = lambda fn, *args: self.encode_queue.append((fn, args))
        source.queue_packet = Mock()
        source._csc_encoder = Mock()
        source._csc_encoder.get_info.return_value = {}
        source._video_encoder = Mock()
        source._video_encoder.get_info.return_value = {}
        source._video_encoder.is_closed.return_value = False
        source._video_encoder.get_type.return_value = "test"
        source._video_encoder.get_encoding.return_value = "h264"
        source._video_encoder.get_width.return_value = 64
        source._video_encoder.get_height.return_value = 64
        source.get_video_encoder_options = Mock(return_value={})

    def schedule(self) -> int:
        source = self.source
        source.schedule_video_encoder_timer(source._video_encoder, source._csc_encoder)
        return self.timer_id()

    def timer_id(self) -> int:
        return self.source.video_encoder_timer

    def run_encode_queue(self) -> None:
        while self.encode_queue:
            fn, args = self.encode_queue.pop(0)
            fn(*args)

    def encode(self, data=b"frame", delayed=0):
        source = self.source
        source.pixel_format = "RGB"
        source.encoding = "h264"
        source.video_helper = Mock()
        source.may_use_scrolling = Mock(return_value=False)
        source.check_pipeline = Mock(return_value=True)
        source.batch_config = Mock(delay=20)
        source.non_video_encodings = ("rgb",)
        source.is_cancelled = Mock(return_value=False)
        source.video_fallback = Mock(return_value=("fallback",))
        image = Mock()
        image.get_geometry.return_value = 0, 0, 64, 64
        image.get_pixel_format.return_value = "RGB"
        source.csc_image = Mock(return_value=(source._csc_encoder, image, "RGB", 64, 64))
        source._video_encoder.compress_image.return_value = data, {"frame": 1, "delayed": delayed}
        return source.do_video_encode("h264", image, typedict())

    def test_timeout_depends_on_pipeline_gpu_use(self) -> None:
        source = self.source
        source.assign_sq_options = dict
        source.datagram = False
        source._current_quality = source._current_speed = 50
        source.full_csc_modes = typedict({"h264": ("RGB",)})
        for encoder_gpu, csc_gpu, delay in ((0, None, 10000), (100, None, 2000), (0, 0, 10000), (0, 100, 2000)):
            for detection in (False, True):
                with self.subTest(encoder_gpu=encoder_gpu, csc_gpu=csc_gpu, detection=detection):
                    encoder_spec = VideoSpec(codec_class=Mock, codec_type="test", encoding="h264",
                                             output_colorspaces=("RGB",), gpu_cost=encoder_gpu)
                    csc_spec = None if csc_gpu is None else CSCSpec(codec_class=Mock, codec_type="test", gpu_cost=csc_gpu)
                    source.video_subregion.detection = detection
                    source.setup_pipeline_option(64, 64, "RGB", 0, (1, 1), (1, 1), 64, 64, csc_spec,
                                                 "RGB", (1, 1), 64, 64, encoder_spec)
                    self.schedule()
                    self.assertEqual(self.scheduler.scheduled[-1][1], delay)

    def test_each_produced_frame_resets_timeout(self) -> None:
        self.encode()
        first = self.timer_id()
        self.encode()
        self.assertNotEqual(self.timer_id(), first)
        self.assertIn(first, self.scheduler.cancelled)
        self.assertEqual(len(self.scheduler.tasks), 1)

    def test_missing_output_keeps_previous_timeout(self) -> None:
        timer = self.schedule()
        with patch.object(video_compress, "videolog"):
            self.encode(data=b"")
        self.assertEqual(self.timer_id(), timer)
        self.assertNotIn(timer, self.scheduler.cancelled)

    def test_encode_failure_keeps_previous_timeout(self) -> None:
        timer = self.schedule()
        self.source._video_encoder.compress_image.side_effect = RuntimeError("test failure")
        with patch.object(video_compress, "videolog"):
            self.assertEqual(self.encode(), ("fallback",))
        self.assertEqual(self.timer_id(), timer)

    def test_timeout_cleans_both_codecs_on_encode_thread(self) -> None:
        source = self.source
        encoder, csc = source._video_encoder, source._csc_encoder
        self.scheduler.fire(self.schedule())
        encoder.clean.assert_not_called()
        csc.clean.assert_not_called()
        self.assertIs(source._video_encoder, encoder)
        self.run_encode_queue()
        encoder.clean.assert_called_once_with()
        csc.clean.assert_called_once_with()
        self.assertIsNone(source._video_encoder)
        self.assertIsNone(source._csc_encoder)
        self.assertEqual(source.video_encoder_timer, 0)
        self.assertEqual(source._video_encoder_timer_sequence, 0)
        self.assertFalse(self.scheduler.tasks)

    def test_timeout_without_csc(self) -> None:
        self.source._csc_encoder = None
        encoder = self.source._video_encoder
        self.scheduler.fire(self.schedule())
        self.run_encode_queue()
        encoder.clean.assert_called_once_with()

    def test_cancelled_ui_callback_cannot_clear_new_timer(self) -> None:
        first = self.schedule()
        callback, args = self.scheduler.tasks[first]
        current = self.schedule()
        callback(*args)
        self.run_encode_queue()
        self.assertEqual(self.timer_id(), current)
        self.source._video_encoder.clean.assert_not_called()

    def test_frame_overtakes_queued_timeout(self) -> None:
        source = self.source
        encoder, csc = source._video_encoder, source._csc_encoder
        self.scheduler.fire(self.schedule())
        self.encode()
        timer = self.timer_id()
        self.run_encode_queue()
        encoder.clean.assert_not_called()
        csc.clean.assert_not_called()
        self.assertEqual(self.timer_id(), timer)
        self.assertIn(timer, self.scheduler.tasks)

    def test_timeout_during_encode_waits_and_checks_for_new_output(self) -> None:
        source = self.source
        encoder, csc = source._video_encoder, source._csc_encoder
        started, finish = Event(), Event()

        def compress(*_args):
            started.set()
            self.assertTrue(finish.wait(5), "encode was not released")
            return b"frame", {"frame": 1}

        encoder.compress_image.side_effect = compress
        timer = self.schedule()
        with ThreadPoolExecutor(max_workers=1) as executor:
            source.call_in_encode_thread = lambda fn, *args: executor.submit(fn, *args)
            result = executor.submit(self.encode)
            try:
                self.assertTrue(started.wait(5), "encode did not start")
                self.scheduler.fire(timer)
                self.assertIs(source._video_encoder, encoder)
                self.assertIs(source._csc_encoder, csc)
                encoder.clean.assert_not_called()
            finally:
                finish.set()
            self.assertEqual(result.result(5)[0], "h264")
            executor.submit(lambda: None).result(5)
            encoder.clean.assert_not_called()
            csc.clean.assert_not_called()

            # The next idle expiry cleans both codecs on that same encode thread.
            thread_id = executor.submit(get_ident).result(5)
            cleaned_on = []
            encoder.clean.side_effect = csc.clean.side_effect = lambda: cleaned_on.append(get_ident())
            self.scheduler.fire(self.timer_id())
            executor.submit(lambda: None).result(5)
            self.assertEqual(cleaned_on, [thread_id, thread_id])

    def test_queued_timeout_ignores_replaced_codecs(self) -> None:
        for replace in ("_video_encoder", "_csc_encoder"):
            with self.subTest(replace=replace):
                source = self.source
                encoder, csc = source._video_encoder, source._csc_encoder
                self.scheduler.fire(self.schedule())
                replacement = Mock()
                setattr(source, replace, replacement)
                self.run_encode_queue()
                encoder.clean.assert_not_called()
                csc.clean.assert_not_called()
                replacement.clean.assert_not_called()
                self.assertIs(getattr(source, replace), replacement)

    def test_cancellation_invalidates_queued_timeout(self) -> None:
        encoder = self.source._video_encoder
        self.scheduler.fire(self.schedule())
        self.source.cancel_video_encoder_timer()
        self.run_encode_queue()
        encoder.clean.assert_not_called()

    def test_frame_with_pending_b_frames_gets_longer_timeout(self) -> None:
        for timeout in (2, 10):
            with self.subTest(timeout=timeout):
                self.source.video_encoder_timeout_delay = timeout
                self.encode(delayed=1)
                self.assertEqual(self.scheduler.scheduled[-1][1], timeout * 2000)
                self.assertTrue(self.source.b_frame_flush_timer)

    def test_timeout_waits_for_pending_or_queued_flush(self) -> None:
        source = self.source
        source.video_encoder_timeout_delay = 2
        self.scheduler.fire(self.schedule())
        source.b_frame_flush_data = source._video_encoder, "RGB", 1, 0, 0, None, False
        # The flush may be queued even though its UI timer has already fired.
        source.b_frame_flush_timer = 0
        self.run_encode_queue()
        source._video_encoder.clean.assert_not_called()
        self.assertEqual(self.scheduler.scheduled[-1][1], 4000)

    def test_flushed_frames_reset_timeout(self) -> None:
        source = self.source
        source.video_encoder_timeout_delay = 2
        source.batch_config = Mock(delay=20)
        source.make_draw_packet = Mock()
        source.queue_damage_packet = Mock()
        for delayed, delay in ((1, 4000), (0, 2000)):
            with self.subTest(delayed=delayed):
                previous = self.schedule()
                source.cancel_video_encoder_flush_timer()
                source.b_frame_flush_data = source._video_encoder, "RGB", 1, 0, 0, None, False
                source._video_encoder.flush.return_value = b"frame", {"delayed": delayed}
                source.do_flush_video_encoder()
                self.assertIn(previous, self.scheduler.cancelled)
                self.assertEqual(self.scheduler.scheduled[-1][1], delay)

    def test_forced_cleanup_invalidates_queued_idle_cleanup(self) -> None:
        source = self.source
        encoder, csc = source._video_encoder, source._csc_encoder
        self.scheduler.fire(self.schedule())
        source.video_context_clean()
        self.run_encode_queue()
        encoder.clean.assert_called_once_with()
        csc.clean.assert_called_once_with()

    def test_detached_encoder_cannot_schedule_timeout(self) -> None:
        source = self.source
        encoder, csc = source._video_encoder, source._csc_encoder
        source.video_context_clean()
        source.schedule_video_encoder_timer(encoder, csc)
        self.assertFalse(self.scheduler.tasks)

    def test_disabled_timeout(self) -> None:
        self.schedule()
        self.source.video_encoder_timeout_delay = 0
        self.schedule()
        self.assertFalse(self.scheduler.tasks)
        self.assertEqual(self.source.video_encoder_timer, 0)
        self.assertEqual(self.source._video_encoder_timer_sequence, 0)


if __name__ == "__main__":
    unittest.main()
