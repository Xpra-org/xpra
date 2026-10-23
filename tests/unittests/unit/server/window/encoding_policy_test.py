#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from dataclasses import replace

from xpra.server.window.encoding_policy import (
    EncodingState, EncodingStrategy, EncodingStrategyState,
    select_encoding_strategy, select_auto_encoding, select_transparent_encoding,
)


class EncodingStrategyTest(unittest.TestCase):
    state = EncodingStrategyState(common_encodings=("rgb24", "rgb32", "png", "png/L", "png/P", "webp"))

    def test_controls_and_precedence(self):
        for changes, expected in (
            ({"hardcoded": True, "hint_available": True, "using_mmap": True}, EncodingStrategy.HARDCODED),
            ({"hint_available": True, "using_mmap": True}, EncodingStrategy.HINT),
            ({"using_mmap": True, "strict": True, "encoding": "png"}, EncodingStrategy.MMAP),
            ({"encoding": "grayscale", "using_mmap": True}, EncodingStrategy.DEFAULT),
            ({"encoding": "png/L"}, EncodingStrategy.PNG_L),
            ({"encoding": "png/P"}, EncodingStrategy.PNG_P),
            ({"image_depth": 8}, EncodingStrategy.PNG_P),
            ({"image_depth": 8, "encoding": "grayscale"}, EncodingStrategy.PNG_L),
            ({"strict": True, "encoding": "rgb", "want_alpha": True}, EncodingStrategy.RGB32),
            ({"strict": True, "encoding": "rgb"}, EncodingStrategy.RGB24),
            ({"strict": True, "encoding": "rgb", "want_alpha": True, "common_encodings": ("rgb24",)}, EncodingStrategy.RGB24),
            ({"strict": True, "encoding": "png"}, EncodingStrategy.STRICT),
            ({"strict": True, "encoding": "auto"}, EncodingStrategy.DEFAULT),
            ({"strict": True, "encoding": "stream"}, EncodingStrategy.DEFAULT),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(select_encoding_strategy(replace(self.state, **changes)), expected)

    def test_alpha_shape_and_rgb_choices(self):
        for changes, expected in (
            ({"want_alpha": True, "encoding": "rgb"}, EncodingStrategy.RGB32),
            ({"is_tray": True, "encoding": "rgb32"}, EncodingStrategy.RGB32),
            ({"want_alpha": True, "encoding": "png"}, EncodingStrategy.STRICT),
            ({"want_alpha": True, "encoding": "grayscale"}, EncodingStrategy.GRAYSCALE),
            ({"want_alpha": True}, EncodingStrategy.TRANSPARENT),
            ({"is_tray": True}, EncodingStrategy.TRANSPARENT),
            ({"want_alpha": True, "encoding": "rgb", "common_encodings": ("png",)}, EncodingStrategy.TRANSPARENT),
            ({"encoding": "rgb"}, EncodingStrategy.RGB24),
            ({"encoding": "rgb", "common_encodings": ("rgb32",)}, EncodingStrategy.RGB32),
            ({"encoding": "rgb", "has_shape": True}, EncodingStrategy.DEFAULT),
            ({"encoding": "rgb", "common_encodings": ("png",)}, EncodingStrategy.DEFAULT),
            ({}, EncodingStrategy.DEFAULT),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(select_encoding_strategy(replace(self.state, **changes)), expected)

    def test_missing_required_encodings(self):
        for changes in (
            {"image_depth": 8, "encoding": "grayscale", "common_encodings": ("png/P",)},
            {"image_depth": 8, "common_encodings": ("png",)},
            {"strict": True, "encoding": "rgb", "common_encodings": ("rgb32",)},
        ):
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                select_encoding_strategy(replace(self.state, **changes))


class AutoEncodingTest(unittest.TestCase):
    state = EncodingState()

    def test_small_rgb_threshold_and_capabilities(self):
        state = replace(self.state, rgb_auto_threshold=4096)
        encodings = "rgb24", "rgb32", "webp"
        self.assertEqual(select_auto_encoding(state, 63, 64, encodings), "rgb24")
        self.assertEqual(select_auto_encoding(state, 64, 64, encodings), "webp")
        for changes, expected in (
            ({"image_depth": 30, "client_bit_depth": 30}, "rgb32"),
            ({"image_depth": 30, "client_bit_depth": 24}, "rgb24"),
            ({"has_shape": True}, "webp"),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(select_auto_encoding(replace(state, **changes), 63, 64, encodings), expected)
        self.assertEqual(select_auto_encoding(state, 63, 64, ("webp",)), "webp")

    def test_natural_content_quality_and_speed_boundaries(self):
        encodings = "jpeg", "webp", "jph"
        for natural, quality, speed, alpha, expected in (
            (True, 50, 49, False, "jph"),
            (True, 51, 49, False, "webp"),
            (True, 50, 50, False, "webp"),
            (False, 50, 49, False, "webp"),
            (True, 50, 49, True, "webp"),
        ):
            with self.subTest(natural=natural, quality=quality, speed=speed, alpha=alpha):
                state = replace(self.state, natural_content=natural, want_alpha=alpha)
                self.assertEqual(select_auto_encoding(state, 640, 360, encodings, quality=quality, speed=speed), expected)

    def test_webp_cutoff_and_lossless_requests(self):
        encodings = "webp", "jpeg", "jpega", "png"
        self.assertEqual(select_auto_encoding(self.state, 512, 1024, encodings, quality=80), "webp")
        self.assertEqual(select_auto_encoding(self.state, 513, 1024, encodings, quality=80), "jpeg")
        self.assertEqual(select_auto_encoding(self.state, 513, 1024, encodings, quality=100), "webp")
        self.assertEqual(select_auto_encoding(self.state, 512, 1024, encodings, quality=80, webp_efficiency_cutoff=4096), "jpeg")
        for changes in ({"want_alpha": True}, {"is_tray": True}):
            with self.subTest(changes=changes):
                state = replace(self.state, **changes)
                self.assertEqual(select_auto_encoding(state, 1024, 1024, encodings, quality=80), "jpega")
        self.assertEqual(select_auto_encoding(self.state, 1024, 1024, ("jpeg", "png"), quality=100), "png")

    def test_codec_dimension_boundaries(self):
        encodings = "png", "webp", "jpeg"
        for width, height, expected in (
            (1, 2, "png"), (2, 1, "png"), (2, 2, "webp"),
            (16383, 2, "webp"), (16384, 2, "jpeg"), (2, 16384, "jpeg"),
        ):
            with self.subTest(size=(width, height)):
                self.assertEqual(select_auto_encoding(self.state, width, height, encodings, quality=80), expected)

    def test_bit_depth_and_grayscale(self):
        encodings = "png", "rgb32"
        for depth, client_depth, expected in ((30, 30, "rgb32"), (30, 32, "png"), (30, 24, "png"), (32, 30, "rgb32")):
            with self.subTest(depth=depth, client_depth=client_depth):
                state = replace(self.state, image_depth=depth, client_bit_depth=client_depth)
                self.assertEqual(select_auto_encoding(state, 1024, 1024, encodings, quality=100), expected)
        state = replace(self.state, encoding="grayscale", rgb_auto_threshold=10000, natural_content=True)
        self.assertEqual(select_auto_encoding(state, 64, 64, ("webp", "jph", "png"), quality=100, speed=0), "png")

    def test_codec_fallbacks(self):
        for changes, encodings, quality, expected in (
            ({}, ("webp",), 80, "webp"),
            ({}, ("avif",), 80, "avif"),
            ({}, ("jph",), 80, "jph"),
            ({"image_depth": 16}, ("png", "jpeg"), 80, "png"),
            ({"image_depth": 16}, ("jpeg",), 80, "jpeg"),
            ({"image_depth": 16}, ("avif",), 80, "avif"),
        ):
            with self.subTest(changes=changes, encodings=encodings):
                self.assertEqual(select_auto_encoding(replace(self.state, **changes), 1024, 1024,
                                                      encodings, quality=quality), expected)

    def test_current_encoding_and_ordered_fallback(self):
        for encodings, current, expected in (
            (("rgb24", "rgb32"), "rgb32", "rgb32"),
            (("rgb", "rgb32", "rgb24"), "missing", "rgb32"),
            (("rgb", "rgb24", "rgb32"), "missing", "rgb24"),
            (("rgb",), "", "rgb"),
        ):
            with self.subTest(encodings=encodings, current=current):
                self.assertEqual(select_auto_encoding(self.state, 1024, 1024, encodings, current_encoding=current), expected)
        with self.assertRaisesRegex(ValueError, "no options to choose from"):
            select_auto_encoding(self.state, 1024, 1024, ())


class TransparentEncodingTest(unittest.TestCase):
    state = EncodingState(want_alpha=True)

    def test_current_encoding_and_missing_transparency(self):
        self.assertEqual(select_transparent_encoding(self.state, 1024, 1024, (), quality=80, current_encoding="webp"), "webp")
        self.assertEqual(select_transparent_encoding(self.state, 1024, 1024, ("h264",), quality=80, current_encoding="h264"), "h264")
        self.assertIsNone(select_transparent_encoding(self.state, 1024, 1024, ("h264",), quality=80))

    def test_rgb_threshold_depth_and_shape(self):
        encodings = "rgb32", "webp", "png"
        state = replace(self.state, rgb_auto_threshold=4096)
        self.assertEqual(select_transparent_encoding(state, 63, 64, encodings, quality=80), "rgb32")
        self.assertEqual(select_transparent_encoding(state, 64, 64, encodings, quality=80), "webp")
        self.assertEqual(select_transparent_encoding(replace(state, has_shape=True), 63, 64, encodings, quality=80), "webp")
        state = replace(self.state, image_depth=30, client_bit_depth=30)
        self.assertEqual(select_transparent_encoding(state, 1024, 1024, encodings, quality=100), "rgb32")
        self.assertEqual(select_transparent_encoding(replace(state, has_shape=True), 1024, 1024, encodings, quality=100), "webp")

    def test_quality_and_webp_cutoff(self):
        encodings = "webp", "jpega", "png"
        for width, quality, expected in ((512, 80, "webp"), (513, 80, "jpega"), (513, 100, "webp")):
            with self.subTest(width=width, quality=quality):
                self.assertEqual(select_transparent_encoding(self.state, width, 1024, encodings, quality=quality), expected)
        self.assertEqual(select_transparent_encoding(self.state, 512, 1024, encodings, quality=80,
                                                     webp_efficiency_cutoff=4096), "jpega")

    def test_dimensions_and_grayscale(self):
        encodings = "webp", "jpega", "png"
        for width, height, expected in ((1, 2, "png"), (2, 1, "png"), (16383, 2, "webp"), (16384, 2, "jpega"), (2, 16384, "jpega")):
            with self.subTest(size=(width, height)):
                self.assertEqual(select_transparent_encoding(self.state, width, height, encodings, quality=80), expected)
        state = replace(self.state, encoding="grayscale")
        self.assertEqual(select_transparent_encoding(state, 1024, 1024, encodings, quality=100), "png")

    def test_ordered_and_configured_fallbacks(self):
        self.assertEqual(select_transparent_encoding(self.state, 1024, 1024, ("rgb32", "png"), quality=80), "png")
        self.assertEqual(select_transparent_encoding(self.state, 1024, 1024, ("rgb32",), quality=80), "rgb32")
        self.assertEqual(select_transparent_encoding(self.state, 1024, 1024, ("webp",), quality=80), "webp")
        state = replace(self.state, image_depth=16)
        self.assertEqual(select_transparent_encoding(state, 1024, 1024, ("webp",), quality=80), "webp")
        self.assertIsNone(select_transparent_encoding(self.state, 1024, 1024, ("webp", "png"), quality=80, transparency_encodings=()))
        self.assertEqual(select_transparent_encoding(self.state, 1024, 1024, ("webp", "png"), quality=80,
                                                     transparency_encodings=("png",)), "png")


if __name__ == '__main__':
    unittest.main()
