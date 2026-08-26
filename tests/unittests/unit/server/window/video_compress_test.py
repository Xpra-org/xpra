# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.server.window.video_compress import WindowVideoSource


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


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
