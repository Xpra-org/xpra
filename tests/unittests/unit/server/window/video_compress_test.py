# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.window import compress, video_compress
from xpra.server.window.video_compress import WindowVideoSource
from xpra.util.objects import typedict


class PipelineElement:

    def __init__(self, clean_error: bool = False) -> None:
        self.clean_count = 0
        self.clean_error = clean_error

    def clean(self) -> None:
        self.clean_count += 1
        if self.clean_error:
            raise RuntimeError("cleanup failed")


class Converter(PipelineElement):

    def init_context(self, src_width, src_height, _src_format,
                     dst_width, dst_height, _dst_format, _options) -> None:
        self.src_size = src_width, src_height
        self.dst_size = dst_width, dst_height

    def get_info(self) -> dict:
        return {}


class Encoder(PipelineElement):

    def __init__(self, init_started=None, finish_init=None) -> None:
        super().__init__()
        self.init_started = init_started
        self.finish_init = finish_init

    def init_context(self, _encoding, _width, _height, _src_format, _options) -> None:
        if self.init_started:
            self.init_started.set()
        if self.finish_init and not self.finish_init.wait(2):
            raise RuntimeError("encoder setup was not released")

    def get_info(self) -> dict:
        return {}


class EncodeWorker:

    def __init__(self) -> None:
        self.queue: Queue = Queue()
        self.optional: list[bool] = []
        self.callbacks: list = []
        self.errors: list[BaseException] = []
        self.thread = Thread(target=self.run, name="test-encode", daemon=True)
        self.thread.start()

    def call(self, optional: bool, callback, *args) -> None:
        self.optional.append(optional)
        self.callbacks.append(callback)
        self.queue.put((callback, args))

    def run(self) -> None:
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                callback, args = item
                callback(*args)
            except BaseException as e:
                self.errors.append(e)
            finally:
                self.queue.task_done()

    def drain(self) -> None:
        self.queue.join()

    def close(self) -> None:
        self.queue.put(None)
        self.queue.join()
        self.thread.join(2)
        if self.thread.is_alive():
            raise RuntimeError("encode worker did not stop")


class VideoContextCleanTest(unittest.TestCase):

    @staticmethod
    def make_source(csc=None, encoder=None) -> WindowVideoSource:
        source = WindowVideoSource.__new__(WindowVideoSource)
        source._csc_encoder = csc
        source._video_encoder = encoder
        source.cancel_video_encoder_flush = Mock()
        source.cancel_video_encoder_timer = Mock()
        source.call_in_encode_thread = Mock()
        source.csc_clean = Mock()
        source.ve_clean = Mock()
        source.wid = 1
        return source

    def test_cancels_timers_without_a_context(self) -> None:
        source = self.make_source()

        source.video_context_clean()

        source.cancel_video_encoder_flush.assert_called_once_with()
        source.cancel_video_encoder_timer.assert_called_once_with()
        source.call_in_encode_thread.assert_called_once()
        optional, clean = source.call_in_encode_thread.call_args.args
        self.assertFalse(optional)

        clean()

        self.assertEqual(source.cancel_video_encoder_flush.call_count, 2)
        self.assertEqual(source.cancel_video_encoder_timer.call_count, 2)
        source.csc_clean.assert_not_called()
        source.ve_clean.assert_not_called()

    def test_cleans_context_published_after_empty_snapshot(self) -> None:
        source = self.make_source()

        source.video_context_clean()
        optional, clean = source.call_in_encode_thread.call_args.args
        self.assertFalse(optional)

        csc = Mock()
        encoder = Mock()
        source._csc_encoder = csc
        source._video_encoder = encoder
        clean()

        self.assertIsNone(source._csc_encoder)
        self.assertIsNone(source._video_encoder)
        source.csc_clean.assert_called_once_with(csc)
        source.ve_clean.assert_called_once_with(encoder)

    def test_detaches_and_cleans_context(self) -> None:
        csc = Mock()
        encoder = Mock()
        source = self.make_source(csc, encoder)

        source.video_context_clean()

        self.assertIsNone(source._csc_encoder)
        self.assertIsNone(source._video_encoder)
        source.call_in_encode_thread.assert_called_once()
        optional, clean = source.call_in_encode_thread.call_args.args
        self.assertFalse(optional)

        clean()

        self.assertEqual(source.cancel_video_encoder_flush.call_count, 2)
        source.csc_clean.assert_called_once_with(csc)
        source.ve_clean.assert_called_once_with(encoder)

    def test_ve_clean_still_cancels_its_timer(self) -> None:
        encoder = Mock()
        source = self.make_source()

        WindowVideoSource.ve_clean(source, encoder)

        source.cancel_video_encoder_timer.assert_called_once_with()
        encoder.clean.assert_called_once_with()

    def test_closed_encoder_flush_saves_data_before_cleanup(self) -> None:
        source = self.make_source()
        encoder = Mock()
        encoder.is_closed.side_effect = (False, True)
        encoder.get_type.return_value = "test"
        encoder.get_width.return_value = 64
        encoder.get_height.return_value = 64
        encoder.get_encoding.return_value = "h264"
        encoder.flush.return_value = b"data", {}
        source._video_encoder = encoder
        source.b_frame_flush_data = encoder, None, 1, 0, 0, None
        source.b_frame_flush_timer = 0
        source.start_video_frame = 0
        events = []
        source.video_stream_file = Mock()
        source.video_stream_file.write.side_effect = lambda data: events.append(("write", data))
        source.video_context_clean = Mock(side_effect=lambda encode_thread: events.append(("clean", encode_thread)))
        source.make_draw_packet = Mock(return_value=("draw",))
        source.queue_damage_packet = Mock()
        source.schedule_video_encoder_flush = Mock()
        source.schedule_video_encoder_timer = Mock()

        source.do_flush_video_encoder()

        self.assertEqual(events, [("write", b"data"), ("clean", True)])
        source.video_stream_file.flush.assert_called_once_with()
        source.queue_damage_packet.assert_called_once()
        source.schedule_video_encoder_flush.assert_not_called()
        source.schedule_video_encoder_timer.assert_not_called()


class VideoPipelineLifecycleTest(unittest.TestCase):

    @staticmethod
    def make_source() -> WindowVideoSource:
        source = object.__new__(WindowVideoSource)
        source.wid = 7
        source._csc_encoder = None
        source._video_encoder = None
        source.video_encoder_timer = 0
        source.b_frame_flush_timer = 0
        source.b_frame_flush_data = ()
        source.video_stream_file = None
        source.queue_packet = lambda *_args: None
        return source

    @staticmethod
    def setup_pipeline(source, converter, encoder) -> bool:
        source.full_csc_modes = typedict({"h264": ("YUV420P",)})
        source.encoding_options = typedict()
        source.assign_sq_options = lambda options: options
        source._current_speed = 50
        source._current_quality = 50
        source.encoding = "h264"
        source.datagram = 0
        source.get_video_encoder_options = lambda *_args: {}
        csc_spec = SimpleNamespace(
            width_mask=0xFFFF,
            height_mask=0xFFFF,
            min_w=8,
            min_h=8,
            max_w=16384,
            max_h=16384,
            make_instance=lambda: converter,
        )
        encoder_spec = SimpleNamespace(
            encoding="h264",
            output_colorspaces=("YUV420P",),
            width_mask=0xFFFF,
            height_mask=0xFFFF,
            min_w=8,
            min_h=8,
            max_w=16384,
            max_h=16384,
            can_scale=False,
            full_range=False,
            make_instance=lambda: encoder,
        )
        return source.setup_pipeline_option(
            64, 64, "BGRX", 100, (1, 1), (1, 1), 64, 64, csc_spec,
            "YUV420P", (1, 1), 64, 64, encoder_spec,
        )

    def test_cleanup_sweeps_pipeline_published_by_setup(self) -> None:
        for has_old_pipeline in (False, True):
            with self.subTest(has_old_pipeline=has_old_pipeline):
                source = self.make_source()
                worker = EncodeWorker()
                source.call_in_encode_thread = worker.call
                old_csc = Converter(clean_error=has_old_pipeline)
                old_encoder = Encoder()
                if has_old_pipeline:
                    source._csc_encoder = old_csc
                    source._video_encoder = old_encoder
                init_started = Event()
                finish_init = Event()
                new_csc = Converter()
                new_encoder = Encoder(init_started, finish_init)
                worker.call(True, self.setup_pipeline, source, new_csc, new_encoder)
                try:
                    self.assertTrue(init_started.wait(2))
                    source.video_context_clean()
                    self.assertIsNone(source._csc_encoder)
                    self.assertIsNone(source._video_encoder)
                    finish_init.set()
                    worker.drain()

                    self.assertIsNone(source._csc_encoder)
                    self.assertIsNone(source._video_encoder)
                    self.assertEqual(new_csc.clean_count, 1)
                    self.assertEqual(new_encoder.clean_count, 1)
                    self.assertEqual(old_csc.clean_count, int(has_old_pipeline))
                    self.assertEqual(old_encoder.clean_count, int(has_old_pipeline))
                    self.assertEqual(len(worker.errors), int(has_old_pipeline))
                    self.assertFalse(worker.optional[-1])
                finally:
                    finish_init.set()
                    worker.close()

    def test_reinitialization_cleans_existing_pipeline(self) -> None:
        source = self.make_source()
        worker = EncodeWorker()
        source.call_in_encode_thread = worker.call
        source._mmap = True
        old_csc = Converter()
        old_encoder = Encoder()
        worker.call(True, self.setup_pipeline, source, old_csc, old_encoder)
        worker.drain()
        self.assertIs(source._csc_encoder, old_csc)
        self.assertIs(source._video_encoder, old_encoder)
        source._encoders = {}
        source.parse_csc_modes = Mock()
        source.update_encoding_selection = Mock()

        def base_init() -> None:
            self.assertIsNone(source._csc_encoder)
            self.assertIsNone(source._video_encoder)

        try:
            with patch.object(video_compress.WindowSource, "do_init_encoders", side_effect=base_init), \
                    patch.object(video_compress, "has_codec", return_value=False):
                source.init_encoders()
            worker.drain()

            source.parse_csc_modes.assert_called_once_with(None)
            source.update_encoding_selection.assert_called_once_with("h264", init=True)
            self.assertEqual(old_csc.clean_count, 1)
            self.assertEqual(old_encoder.clean_count, 1)
            self.assertEqual(worker.errors, [])
            self.assertFalse(worker.optional[-1])
        finally:
            worker.close()

    def test_full_cleanup_cancels_timer_and_queues_one_barrier(self) -> None:
        source = self.make_source()
        source.init_vars()
        source.av_sync_timer = 0
        source.encode_queue = []
        source.encode_queue_max_size = 10
        source._mmap = None
        source.statistics = SimpleNamespace(encoding_totals={}, encoding_pending={})
        batch_cleaned = []
        source.batch_config = SimpleNamespace(cleanup=lambda: batch_cleaned.append(True))
        source.queue_packet = lambda *_args: None
        worker = EncodeWorker()
        source.call_in_encode_thread = worker.call
        old_csc = Converter()
        old_encoder = Encoder()
        worker.call(True, self.setup_pipeline, source, old_csc, old_encoder)
        worker.drain()
        self.assertIs(source._csc_encoder, old_csc)
        self.assertIs(source._video_encoder, old_encoder)
        worker_started = Event()
        finish_work = Event()

        def hold_worker() -> None:
            worker_started.set()
            if not finish_work.wait(2):
                raise RuntimeError("encode worker was not released")

        worker.call(False, hold_worker)
        self.assertTrue(worker_started.wait(2))
        removed_sources = []
        idle_callbacks = []
        fake_glib = SimpleNamespace(
            timeout_add=lambda _delay, _callback: 101,
            source_remove=removed_sources.append,
            idle_add=lambda callback: idle_callbacks.append(callback),
        )
        try:
            with patch.object(video_compress, "GLib", fake_glib), \
                    patch.object(compress, "GLib", fake_glib):
                source.schedule_video_encoder_timer()
                self.assertEqual(source.video_encoder_timer, 101)
                source.cleanup()
                self.assertEqual(removed_sources, [101])
                finish_work.set()
                worker.drain()

            self.assertEqual(batch_cleaned, [True])
            self.assertEqual(old_csc.clean_count, 1)
            self.assertEqual(old_encoder.clean_count, 1)
            self.assertIsNone(source._csc_encoder)
            self.assertIsNone(source._video_encoder)
            self.assertEqual(worker.errors, [])
            self.assertEqual(len(idle_callbacks), 1)
            self.assertEqual(worker.optional, [True, False, False, False, False])
            self.assertEqual(
                [callback.__name__ for callback in worker.callbacks],
                ["setup_pipeline", "hold_worker", "do_free_scroll_data", "clean", "encode_ended"],
            )
        finally:
            finish_work.set()
            worker.close()


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
