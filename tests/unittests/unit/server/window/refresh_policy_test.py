#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from dataclasses import replace

from xpra.server.window.refresh import RefreshSettings, classify_refresh, get_refresh_delay


class RefreshPolicyTest(unittest.TestCase):
    lossy_formats = ("NV12", "YUV420P", "YUVA420P", "YUV422P", "YUVA422P")

    def classify(self, encoding, depth=24, options=None, quality=100, true_lossless=False):
        return classify_refresh(encoding, depth, options or {}, refresh_quality=quality,
                                true_lossless=true_lossless, lossy_formats=self.lossy_formats)

    def test_png_depth_and_lossless_transports(self):
        for depth, lossy in ((8, False), (16, False), (24, False), (30, True), (32, False), (48, True)):
            with self.subTest(depth=depth):
                self.assertEqual(self.classify("png", depth), (100, lossy))
        for encoding in ("png/P", "png/L", "rgb24", "rgb32", "mmap"):
            with self.subTest(encoding=encoding):
                options = {"quality": 0, "csc": "YUV420P", "scaled_size": (10, 10)}
                self.assertEqual(self.classify(encoding, options=options), (100, False))

    def test_quality_threshold(self):
        self.assertEqual(self.classify("webp"), (0, True))
        self.assertEqual(self.classify("webp", options={"quality": 99}), (99, True))
        self.assertEqual(self.classify("webp", options={"quality": 100}), (100, False))
        self.assertEqual(self.classify("webp", options={"quality": 90}, quality=90), (90, False))

    def test_csc_and_scaling_can_be_lossy_at_full_quality(self):
        for csc in self.lossy_formats:
            with self.subTest(csc=csc):
                self.assertEqual(self.classify("h264", options={"quality": 100, "csc": csc}), (100, True))
        self.assertEqual(self.classify("h264", options={"quality": 100, "csc": "YUV444P"}), (100, False))
        for scaled_size, lossy in ((None, False), ((10, 10), True), ((), True)):
            with self.subTest(scaled_size=scaled_size):
                self.assertEqual(self.classify("webp", options={"quality": 100, "scaled_size": scaled_size}), (100, lossy))

    def test_true_lossless_jpeg(self):
        self.assertEqual(self.classify("jpeg", options={"quality": 100}), (100, False))
        self.assertEqual(self.classify("jpeg", options={"quality": 100}, true_lossless=True), (100, True))
        self.assertEqual(self.classify("webp", options={"quality": 100}, true_lossless=True), (100, False))

    def test_initial_delay_uses_congestion_and_floors(self):
        settings = RefreshSettings(100, 100, 200)
        for percent, congestion, expected in ((25, 0, 50), (100, 0, 200), (25, 3, 200), (100, 8, 600)):
            with self.subTest(percent=percent, congestion=congestion):
                self.assertEqual(get_refresh_delay(replace(settings, congestion=congestion), percent, initial=True), expected)
        self.assertEqual(get_refresh_delay(replace(settings, min_delay=500), 100, initial=True), 500)
        self.assertEqual(get_refresh_delay(replace(settings, batch_delay=31), 25, initial=True), 155)

    def test_extension_delay_keeps_small_updates_from_advancing_deadline(self):
        settings = RefreshSettings(100, 100, 200)
        for percent, expected in ((0, 50), (25, 50), (75, 150), (100, 200), (200, 400)):
            with self.subTest(percent=percent):
                self.assertEqual(get_refresh_delay(settings, percent), expected)
        self.assertEqual(get_refresh_delay(replace(settings, congestion=10), 25), 50)
        self.assertEqual(get_refresh_delay(replace(settings, batch_delay=31), 25), 155)


if __name__ == '__main__':
    unittest.main()
