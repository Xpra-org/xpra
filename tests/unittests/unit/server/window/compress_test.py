#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
