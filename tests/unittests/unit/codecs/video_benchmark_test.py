#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
import json
import unittest
from io import StringIO

from tests.xpra.codecs.benchmark_video_encoders import (
    make_frame,
    psnr_db,
    Result,
    rgb_energy,
    snr_db,
    write_json,
    write_markdown,
)


class VideoBenchmarkTest(unittest.TestCase):

    RESULT = Result("h264", "x264", "openh264", "BGRX->YUV420P->YUV420P->BGRX",
                    640, 360, 80, 50, 10, 12345, 1234.5,
                    31.25, math.inf, 0.4, 1.2, 2.3)

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

    def test_markdown_export(self):
        output = StringIO()
        write_markdown([self.RESULT], output)
        table = output.getvalue()
        self.assertIn("| Encoding | Encoder |", table)
        self.assertIn("| h264 | x264 | openh264 |", table)
        self.assertIn("| 640x360 | 80 | 50 |", table)
        self.assertIn("lossless", table)

    def test_json_export_is_strict_and_has_metadata(self):
        output = StringIO()
        write_json([self.RESULT], {"width": 640, "height": 360}, output)
        document = json.loads(output.getvalue())
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["benchmark"]["width"], 640)
        self.assertEqual(document["results"][0]["encoder"], "x264")
        self.assertIsNone(document["results"][0]["psnr_db"])


if __name__ == "__main__":
    unittest.main()
