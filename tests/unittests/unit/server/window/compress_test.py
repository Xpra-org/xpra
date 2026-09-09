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


class CompressTest(unittest.TestCase):

    @staticmethod
    def make_source(content_types=()) -> WindowSource:
        source = object.__new__(WindowSource)
        source._fixed_speed = -1
        source._fixed_min_speed = 0
        source._fixed_max_speed = 100
        source._current_speed = 50
        source._fixed_quality = -1
        source._quality_hint = -1
        source._fixed_min_quality = 0
        source._fixed_max_quality = 100
        source._current_quality = 80
        source._lossless_threshold_base = 70
        source.statistics = SimpleNamespace(last_packet_time=100)
        source.get_packets_backlog = lambda: 0
        source.content_types = content_types
        source.rgb_formats = ("RGB",)
        source.rgb_lz4 = False
        source.rgb_zstd = False
        source.encoding = "auto"
        source.supports_transparency = True
        source.image_depth = 24
        source._want_alpha = False
        source.is_tray = False
        source._rgb_auto_threshold = 0
        source.has_shape = False
        source.client_bit_depth = 24
        return source

    @staticmethod
    def make_window(has_alpha=True, frame_has_alpha=True, frame_property=True):
        """ a window model exposing `frame-has-alpha` the way the wayland models do """
        return SimpleNamespace(
            has_alpha=lambda: has_alpha,
            get_internal_property_names=lambda: ["frame-has-alpha"] if frame_property else [],
            get_property=lambda name: {"frame-has-alpha": frame_has_alpha}[name],
        )

    def make_alpha_source(self, **window_kwargs) -> WindowSource:
        source = self.make_source()
        source.window = self.make_window(**window_kwargs)
        source.is_OR = False
        source.window_type = set()
        source.window_dimensions = 800, 600
        return source

    def test_an_opaque_buffer_gives_up_the_alpha_channel(self) -> None:
        for has_alpha, frame_has_alpha, expected in (
                (True, True, True),
                (True, False, False),
                # the frame can only narrow the capability, never widen it:
                (False, True, False),
                (False, False, False),
        ):
            with self.subTest(has_alpha=has_alpha, frame_has_alpha=frame_has_alpha):
                source = self.make_alpha_source(has_alpha=has_alpha, frame_has_alpha=frame_has_alpha)
                source.update_has_alpha()
                self.assertEqual(source.has_alpha, expected)

    def test_a_window_without_frame_alpha_keeps_its_capability(self) -> None:
        # ie: an x11 window, whose alpha is decided once by its depth
        source = self.make_alpha_source(has_alpha=True, frame_has_alpha=False, frame_property=False)
        source.update_has_alpha()
        self.assertTrue(source.has_alpha)

    def test_wanting_alpha_hides_the_video_selection(self) -> None:
        # `get_transparent_encoding` only ever returns a `TRANSPARENCY_ENCODINGS` value,
        # and it is returned before `get_best_encoding_impl_default` - the one method
        # `WindowVideoSource` overrides to offer video - can be reached at all:
        source = self.make_source()
        source._encoding_hint = ""
        source._encoders = {}
        source._mmap = None
        source.strict = False
        source.common_encodings = ("rgb24", "rgb32", "png", "webp", "h264")
        source._want_alpha = True
        self.assertEqual(source.get_best_encoding_impl(), source.get_transparent_encoding)
        source._want_alpha = False
        self.assertEqual(source.get_best_encoding_impl(), source.get_auto_encoding)

    @staticmethod
    def make_cancellable_source() -> WindowSource:
        source = object.__new__(WindowSource)
        source.wid = 1
        source._sequence = 5
        source._damage_cancelled = 0
        source._damage_delayed = None
        source.encode_queue = []
        source.refresh_regions = []
        source.refresh_event_time = 0
        for timer in ("expire_timer", "may_send_timer", "soft_timer", "refresh_timer",
                      "timeout_timer", "av_sync_timer", "decode_error_refresh_timer"):
            setattr(source, timer, 0)
        source.statistics = SimpleNamespace(encoding_pending={})
        source.window = Mock()
        return source

    def test_dropping_a_delayed_region_acknowledges_it(self) -> None:
        # nothing else will: `send_delayed_regions` is never going to run for it,
        # and a wayland client throttles its rendering on that acknowledgement
        source = self.make_cancellable_source()
        source._damage_delayed = "some delayed regions"

        source.cancel_damage()

        self.assertIsNone(source._damage_delayed)
        source.window.acknowledge_changes.assert_called_once_with()

    def test_cancelling_without_a_delayed_region_acknowledges_nothing(self) -> None:
        # anything already extracted was acknowledged before it was extracted,
        # so there is nothing outstanding to answer for here
        source = self.make_cancellable_source()

        source.cancel_damage()

        source.window.acknowledge_changes.assert_not_called()

    @patch.object(compress, "monotonic", return_value=100)
    def test_automatic_screen_quality_is_promoted(self, _monotonic) -> None:
        for content_types in ((), ("browser",), ("desktop",)):
            with self.subTest(content_types=content_types):
                source = self.make_source(content_types)
                options = {}
                assigned = source.assign_sq_options(options)
                self.assertEqual(assigned["quality"], 100)
                self.assertNotIn("quality", options)

    @patch.object(compress, "monotonic", return_value=100)
    def test_natural_content_quality_is_not_promoted(self, _monotonic) -> None:
        for content_types in (("video",), ("picture",)):
            with self.subTest(content_types=content_types):
                source = self.make_source(content_types)
                assigned = source.assign_sq_options({})
                self.assertEqual(assigned["quality"], 80)

    @patch.object(compress, "monotonic", return_value=100)
    def test_explicit_or_fixed_quality_is_not_promoted(self, _monotonic) -> None:
        source = self.make_source(("browser",))
        assigned = source.assign_sq_options({"quality": 80})
        self.assertEqual(assigned["quality"], 80)

        source._fixed_quality = 80
        assigned = source.assign_sq_options({})
        self.assertEqual(assigned["quality"], 80)

        source._fixed_quality = -1
        source._quality_hint = 80
        assigned = source.assign_sq_options({})
        self.assertEqual(assigned["quality"], 80)

    @patch.object(compress, "monotonic", return_value=100)
    def test_auto_encoding_uses_assigned_quality(self, _monotonic) -> None:
        encodings = ("jpeg", "webp")
        source = self.make_source(("browser",))
        options = source.assign_sq_options({})
        self.assertEqual(options["quality"], 100)
        self.assertEqual(source.do_get_auto_encoding(1024, 1024, options, "", encodings), "webp")

        options = source.assign_sq_options({"quality": 80})
        self.assertEqual(options["quality"], 80)
        self.assertEqual(source.do_get_auto_encoding(1024, 1024, options, "", encodings), "jpeg")

    @patch.object(compress, "TRUE_LOSSLESS", False)
    def test_lossless_quality_never_uses_jpeg(self) -> None:
        source = self.make_source()
        options = {"quality": 100, "speed": 50}
        self.assertEqual(source.do_get_auto_encoding(1024, 1024, options, "", ("jpeg", "png")), "png")

        source.supports_transparency = True
        source.common_encodings = ("jpega", "png")
        self.assertEqual(source.get_transparent_encoding(1024, 1024, options, "auto"), "png")

    def test_continuous_tone_encoding(self) -> None:
        encodings = ("jpeg", "webp", "jph")
        cases = (
            (("picture",), 30, 20, False, 640, 360, "jph"),
            (("picture",), 50, 20, False, 640, 360, "jph"),
            (("picture",), 51, 20, False, 640, 360, "webp"),
            (("picture",), 50, 50, False, 640, 360, "webp"),
            (("video",), 30, 20, False, 640, 360, "jph"),
            (("browser",), 30, 20, False, 640, 360, "webp"),
            ((), 30, 20, False, 640, 360, "webp"),
            (("picture",), 30, 20, True, 640, 360, "webp"),
            (("browser",), 30, 20, False, 1024, 1024, "jpeg"),
            (("picture",), 100, 20, False, 640, 360, "webp"),
        )
        for content_types, quality, speed, alpha, width, height, expected in cases:
            with self.subTest(
                content_types=content_types, quality=quality, speed=speed,
                alpha=alpha, size=(width, height),
            ):
                source = self.make_source(content_types)
                source._want_alpha = alpha
                options = {"quality": quality, "speed": speed}
                encoding = source.do_get_auto_encoding(width, height, options, "", encodings)
                self.assertEqual(encoding, expected)

    @patch.object(compress, "TRUE_LOSSLESS", False)
    def test_transparent_lossless_webp_ignores_size_cutoff(self) -> None:
        source = self.make_source(("browser",))
        source.common_encodings = ("webp", "jpega")
        size = (1024, 1024)
        self.assertEqual(source.get_transparent_encoding(*size, {"quality": 100}, "auto"), "webp")
        self.assertEqual(source.get_transparent_encoding(*size, {"quality": 80}, "auto"), "jpega")


if __name__ == "__main__":
    unittest.main()
