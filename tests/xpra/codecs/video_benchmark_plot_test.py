#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

if __package__:
    from .plot_video_encoder_benchmarks import color, render_svg, safe_filename
else:
    from plot_video_encoder_benchmarks import color, render_svg, safe_filename


class VideoBenchmarkPlotTest(unittest.TestCase):

    ROWS = [
        {"encoding": "h264", "encoder": "x264", "pipeline": "BGRX->YUV420P",
         "quality": quality, "speed": speed, "encode_ms": latency,
         "roundtrip_ms": latency + 1, "csc_ms": 0.2, "snr_db": 20 + quality / 10,
         "width": 100, "height": 50, "bytes_per_frame": 1000 + speed}
        for quality, values in ((20, ((20, 8.0), (80, 2.0))), (80, ((20, 12.0), (80, 3.0))))
        for speed, latency in values
    ]

    def test_quality_controls_color_intensity(self):
        self.assertNotEqual(color(0, 20), color(0, 80))
        self.assertTrue(color(0, 20).startswith("hsl(210 "))
        self.assertTrue(color(1, 20).startswith("hsl(15 "))

    def test_render_svg(self):
        svg = render_svg("h264", self.ROWS, "encode_ms")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("h264: speed setting vs encode latency", svg)
        self.assertIn("x264, q=20", svg)
        self.assertEqual(svg.count("<polyline"), 2)
        self.assertEqual(svg.count("<circle"), 4)

    def test_render_quality_plots(self):
        for metric, label in (("snr_db", "SNR (dB)"),
                              ("compression_ratio", "Compression ratio")):
            with self.subTest(metric=metric):
                svg = render_svg("h264", self.ROWS, metric)
                self.assertIn(f"h264: quality setting vs {label.lower()}", svg)
                self.assertIn(">Quality setting</text>", svg)
                self.assertIn(">Encoder / speed</text>", svg)
                self.assertIn("x264, s=20", svg)
                self.assertEqual(svg.count("<polyline"), 2)
                self.assertEqual(svg.count("<circle"), 4)

    def test_safe_filename(self):
        self.assertEqual(safe_filename("h264/main"), "h264-main")


if __name__ == "__main__":
    unittest.main()
