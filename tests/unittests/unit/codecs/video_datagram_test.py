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


class VideoDatagramDecodeTest(unittest.TestCase):
    """
    The decoder conceals the slices that are missing from frames re-assembled from fragments:
    a damaged frame may not produce an image, but it must not break the frames that follow.
    """

    def test_openh264_conceals_missing_slices(self):
        encoder_module = load_encoder("openh264")
        try:
            decoder_module = import_module("xpra.codecs.openh264.decoder")
        except ImportError:
            decoder_module = None
        if not encoder_module or not decoder_module:
            self.skipTest("openh264 is not available")
        encoder = encoder_module.Encoder()
        encoder.init_context("h264", WIDTH, HEIGHT, "YUV420P", typedict({"datagram": DATAGRAM, "quality": 50}))
        self.addCleanup(encoder.clean)
        decoder = decoder_module.Decoder()
        decoder.init_context("h264", WIDTH, HEIGHT, "YUV420P", typedict())
        self.addCleanup(decoder.clean)
        rng = Random(4)
        base = noisy_image(rng, 0)
        planes = [bytearray(base.get_plane(i)) for i in range(3)]
        concealed = 0
        for i in range(8):
            # move a small block so the P-frames have several slices:
            planes[0][i * 1000:i * 1000 + 3000] = rng.randbytes(3000)
            image = make_test_image("YUV420P", WIDTH, HEIGHT)
            image.set_pixels(tuple(bytes(p) for p in planes))
            image.set_timestamp(i * 40)
            data, client_options = encoder.compress_image(image, typedict())
            nals = client_options["nals"]
            options = typedict({"fragments": len(nals)})
            if i >= 2 and len(nals) > 2:
                # drop one slice from the middle of this frame:
                start, end = nals[len(nals) // 2 - 1], nals[len(nals) // 2]
                data = data[:start] + data[end:]
                options["missing-fragments"] = (len(nals) // 2, )
                concealed += 1
            damaged = "missing-fragments" in options
            image = decoder.decompress_image(data, options)
            if not damaged:
                self.assertIsNotNone(image, f"frame {i} was not decoded")
        self.assertGreater(concealed, 0, "no frame had enough slices to drop one")

    def test_openh264_damage_is_an_error_without_fragments(self):
        try:
            decoder_module = import_module("xpra.codecs.openh264.decoder")
        except ImportError:
            self.skipTest("openh264 decoder is not available")
        decoder = decoder_module.Decoder()
        decoder.init_context("h264", WIDTH, HEIGHT, "YUV420P", typedict())
        self.addCleanup(decoder.clean)
        # a P-slice without any reference frame:
        with self.assertRaises(RuntimeError):
            decoder.decompress_image(b"\0\0\0\x01\x41\x9a\x00\x10" * 4, typedict())


def main():
    unittest.main()


if __name__ == '__main__':
    main()
