#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import json
import math
import unittest
from io import StringIO
from pathlib import Path

from PIL import Image

if __package__:
    from .benchmark_single_picture_encoders import (
        Result,
        alpha_energy,
        image_to_rgba,
        load_fixtures,
        make_edge_mask,
        pack_bgrx,
        pareto_indices,
        percentile95,
        psnr_db,
        rgb_energy,
        snr_db,
        write_json,
        write_markdown,
    )
    from .generate_picture_benchmark_fixtures import GENERATORS
else:
    from benchmark_single_picture_encoders import (
        Result,
        alpha_energy,
        image_to_rgba,
        load_fixtures,
        make_edge_mask,
        pack_bgrx,
        pareto_indices,
        percentile95,
        psnr_db,
        rgb_energy,
        snr_db,
        write_json,
        write_markdown,
    )
    from generate_picture_benchmark_fixtures import GENERATORS


class PictureBenchmarkTest(unittest.TestCase):

    @staticmethod
    def result(quality: float, size: int, encode_ms: float, decode_ms: float = 1) -> Result:
        return Result(
            scenario="screen", fixture="screen.png", content_types=("text",),
            quality_metric="edge_psnr_db", has_alpha=False, width=10, height=10,
            encoder="test", decoder="test", requested_encoding="test", encoding="test",
            quality=50, speed=50, frames=3, raw_bytes=400, encoded_bytes=size,
            compression_ratio=size / 400, bits_per_pixel=size * 8 / 100,
            encode_ms=encode_ms, encode_p95_ms=encode_ms,
            decode_ms=decode_ms, decode_p95_ms=decode_ms,
            rgb_snr_db=quality, rgb_psnr_db=quality, edge_psnr_db=quality,
            max_rgb_error=1, edge_max_rgb_error=1,
            alpha_psnr_db=None, max_alpha_error=None, alpha_exact=None, lossless=False,
        )

    def test_energy_and_quality_metrics(self):
        reference = bytes((10, 20, 30, 40, 100, 110, 120, 130))
        identical = bytes(reference)
        signal, noise, samples, maximum = rgb_energy(reference, identical)
        self.assertGreater(signal, 0)
        self.assertEqual((noise, samples, maximum), (0, 6, 0))
        self.assertTrue(math.isinf(snr_db(signal, noise)))
        self.assertTrue(math.isinf(psnr_db(noise, samples)))

        candidate = bytes((7, 20, 30, 35, 100, 110, 120, 125))
        _signal, noise, samples, maximum = rgb_energy(reference, candidate, bytes((1, 0)))
        self.assertEqual((noise, samples, maximum), (9, 3, 3))
        alpha_noise, alpha_samples, alpha_maximum = alpha_energy(reference, candidate)
        self.assertEqual((alpha_noise, alpha_samples, alpha_maximum), (50, 2, 5))

    def test_edge_mask_selects_ten_percent(self):
        width, height = 10, 10
        rgba = bytearray(width * height * 4)
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * 4
                rgba[offset:offset + 4] = bytes((x * 20, y * 20, (x + y) * 10, 255))
        mask = make_edge_mask(bytes(rgba), width, height)
        self.assertEqual(len(mask), width * height)
        self.assertEqual(sum(mask), width * height // 10)

    def test_packed_pixel_roundtrip(self):
        rgba = bytes((10, 20, 30, 255, 40, 50, 60, 128))
        opaque_format, opaque = pack_bgrx(rgba, False)
        self.assertEqual(image_to_rgba(opaque_format, opaque, 2, 1, 8),
                         bytes((10, 20, 30, 255, 40, 50, 60, 255)))
        alpha_format, alpha = pack_bgrx(rgba, True)
        self.assertEqual(image_to_rgba(alpha_format, alpha, 2, 1, 8), rgba)

    def test_percentile_and_pareto_frontier(self):
        self.assertEqual(percentile95([5, 1, 2, 4, 3]), 5)
        results = [
            self.result(30, 100, 2),
            self.result(20, 120, 3),
            self.result(40, 150, 4),
        ]
        self.assertEqual(pareto_indices(results), {0, 2})

    def test_exports_are_strict(self):
        result = self.result(math.inf, 100, 2)
        result = Result(**(result.__dict__ | {"lossless": True}))
        output = StringIO()
        write_json([result], {"fixture": "screen"}, output)
        document = json.loads(output.getvalue())
        self.assertEqual(document["schema_version"], 1)
        self.assertIsNone(document["results"][0]["rgb_psnr_db"])
        self.assertTrue(document["results"][0]["lossless"])
        self.assertTrue(document["results"][0]["pareto"])

        output = StringIO()
        write_markdown([result], output)
        self.assertIn("| Scenario | Encoder |", output.getvalue())
        self.assertIn("lossless", output.getvalue())

    def test_committed_fixtures_match_generator(self):
        fixtures = load_fixtures()
        self.assertEqual({fixture.filename for fixture in fixtures}, set(GENERATORS))
        directory = Path(__file__).resolve().parents[2] / "test-images" / "codec-benchmark"
        for filename, make_image in GENERATORS.items():
            with self.subTest(filename=filename):
                expected = make_image()
                with Image.open(directory / filename) as source:
                    actual = source.convert("RGBA")
                self.assertEqual(actual.size, expected.size)
                self.assertEqual(actual.tobytes(), expected.tobytes())


if __name__ == "__main__":
    unittest.main()
