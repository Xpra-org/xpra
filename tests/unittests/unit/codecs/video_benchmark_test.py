#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
import unittest

from tests.xpra.codecs.benchmark_video_encoders import (
    make_frame,
    psnr_db,
    rgb_energy,
    snr_db,
)


class VideoBenchmarkTest(unittest.TestCase):

    def test_stream_is_reproducible_and_moves(self):
        first = make_frame(32, 24, 7)
        same = make_frame(32, 24, 7)
        next_frame = make_frame(32, 24, 8)
        try:
            self.assertEqual(bytes(first.get_pixels()), bytes(same.get_pixels()))
            self.assertNotEqual(bytes(first.get_pixels()), bytes(next_frame.get_pixels()))
        finally:
            first.free()
            same.free()
            next_frame.free()

    def test_metrics(self):
        frame = make_frame(16, 16, 0)
        try:
            signal, noise = rgb_energy(frame, frame)
        finally:
            frame.free()
        self.assertGreater(signal, 0)
        self.assertEqual(noise, 0)
        self.assertTrue(math.isinf(snr_db(signal, noise)))
        self.assertTrue(math.isinf(psnr_db(noise, 16 * 16 * 3)))
        self.assertAlmostEqual(snr_db(100, 10), 10.0)
        self.assertAlmostEqual(psnr_db(10, 10), 10 * math.log10(255 * 255))


if __name__ == "__main__":
    unittest.main()
