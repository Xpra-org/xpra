#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Video encoders in `datagram` mode: each slice must fit in a datagram,
the slice boundaries are exported so the frame can be split on them,
and the encoder can recover from the loss of a frame.
"""

import unittest
from importlib import import_module
from random import Random

from xpra.codecs.checks import make_test_image
from xpra.util.objects import typedict

DATAGRAM = 1100
WIDTH, HEIGHT = 320, 240


def load_encoder(name: str):
    try:
        return import_module(f"xpra.codecs.{name}.encoder")
    except ImportError:
        return None


def noisy_image(rng: Random, timestamp: int):
    image = make_test_image("YUV420P", WIDTH, HEIGHT)
    planes = tuple(image.get_plane(i) for i in range(image.get_planes()))
    image.set_pixels(tuple(rng.randbytes(len(plane)) for plane in planes))
    image.set_timestamp(timestamp)
    return image


class VideoDatagramTest(unittest.TestCase):

    def make_encoder(self, name: str, **options):
        module = load_encoder(name)
        if not module:
            self.skipTest(f"{name} encoder is not available")
        encoder = module.Encoder()
        encoder.init_context("h264", WIDTH, HEIGHT, "YUV420P", typedict(options))
        self.addCleanup(encoder.clean)
        return encoder

    def check_slices(self, name: str, strict=True) -> None:
        encoder = self.make_encoder(name, datagram=DATAGRAM, quality=50, speed=50)
        rng = Random(1)
        for i in range(4):
            data, client_options = encoder.compress_image(noisy_image(rng, i * 40), typedict())
            if not data:
                continue
            nals = client_options.get("nals")
            self.assertTrue(nals, f"{name} did not export the nal boundaries")
            self.assertEqual(nals[-1], len(data))
            self.assertGreater(len(nals), 2, f"{name} frame {i} of {len(data)} bytes was not sliced")
            start = 0
            for index, end in enumerate(nals):
                self.assertGreater(end, start)
                # openh264's limit is not enforced for the last slice of the frame,
                # the fragmentation layer must cope with nals that do not fit:
                if strict or index < len(nals) - 1:
                    self.assertLessEqual(end - start, DATAGRAM, f"{name} nal too big in frame {i}: {nals}")
                start = end
        info = encoder.get_info()
        self.assertEqual(info.get("datagram"), DATAGRAM)

    def check_no_nals_by_default(self, name: str) -> None:
        encoder = self.make_encoder(name, quality=50, speed=50)
        data, client_options = encoder.compress_image(noisy_image(Random(2), 0), typedict())
        self.assertTrue(data)
        self.assertNotIn("nals", client_options)
        self.assertNotIn("datagram", encoder.get_info())

    def check_recovery(self, name: str, expected_method: str) -> None:
        encoder = self.make_encoder(name, datagram=DATAGRAM, quality=50, speed=50)
        rng = Random(3)
        sent = []
        for i in range(6):
            data, client_options = encoder.compress_image(noisy_image(rng, i * 40), typedict())
            sent.append(client_options)
        # pretend the client lost the last frame:
        encoder.request_recovery(sent[-1].get("pts", 0))
        data, client_options = encoder.compress_image(noisy_image(rng, 6 * 40), typedict())
        self.assertTrue(data)
        recovery = encoder.get_info().get("recovery", {})
        self.assertEqual(recovery.get(expected_method), 1, f"{name} recovery={recovery}")
        if expected_method == "keyframe":
            self.assertEqual(client_options.get("type"), "IDR")
        # recovery requests are only applied once:
        encoder.compress_image(noisy_image(rng, 7 * 40), typedict())
        self.assertEqual(sum(encoder.get_info().get("recovery", {}).values()), 1)

    def test_x264_slices(self):
        self.check_slices("x264")

    def test_x264_no_nals_by_default(self):
        self.check_no_nals_by_default("x264")

    def test_x264_no_b_frames(self):
        encoder = self.make_encoder("x264", datagram=DATAGRAM, **{"b-frames": 1})
        self.assertEqual(encoder.get_info()["b-frames"], 0)

    def test_x264_recovery(self):
        self.check_recovery("x264", "invalidated")

    def test_openh264_slices(self):
        self.check_slices("openh264", strict=False)

    def test_openh264_no_nals_by_default(self):
        self.check_no_nals_by_default("openh264")

    def test_openh264_recovery(self):
        self.check_recovery("openh264", "keyframe")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
