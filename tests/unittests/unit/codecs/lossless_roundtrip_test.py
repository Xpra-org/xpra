#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Inspired by tests/xpra/codecs/benchmark_single_picture_encoders.py:
# compress a single large picture at 100% quality with a range of speed settings,
# decompress it again and verify that the round-trip is bit-for-bit lossless.

import unittest
from pathlib import Path

try:
    from PIL import Image, ImageChops
except ImportError:
    Image = None

from xpra.util.objects import typedict
from xpra.codecs import loader
from xpra.codecs.image import ImageWrapper

QUALITY = 100
SPEEDS = (0, 50, 99, 100)

# (encoder, encoding, decoder) picture-codec round-trips that are lossless at quality=100:
LOSSLESS_COMBOS = (
    ("enc_pillow", "png", "dec_pillow"),
    ("enc_pillow", "webp", "dec_pillow"),
    ("enc_webp", "webp", "dec_webp"),
    ("enc_jph", "jph", "dec_jph"),
    ("enc_avif", "avif", "dec_avif"),
)

# a single large picture from the documentation screenshots:
IMAGE = "docs/images/screenshots/win11-glxspheres.png"


def find_image() -> Path | None:
    # tests/unittests/unit/codecs/<this file> -> repo root is 4 levels up:
    path = Path(__file__).resolve().parents[4] / IMAGE
    return path if path.exists() else None


def packet_bytes(data) -> bytes:
    # encoders return a Compressed wrapper (with a .data attribute) or raw bytes:
    payload = getattr(data, "data", data)
    return bytes(payload)


class LosslessRoundtripTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if Image is None:
            raise unittest.SkipTest("python-pillow is required for this test")
        path = find_image()
        if not path:
            raise unittest.SkipTest(f"test image not found: {IMAGE}")
        with Image.open(path) as src:
            rgba = src.convert("RGBA")
        cls.width, cls.height = rgba.size
        cls.has_alpha = rgba.getchannel("A").getextrema() != (255, 255)
        cls.src_format = "BGRA" if cls.has_alpha else "BGRX"
        cls.canon_mode = "RGBA" if cls.has_alpha else "RGB"
        cls.stride = cls.width * 4
        # the colour pixels, and the reference we compare every decoded frame against:
        cls.pixels = cls.pack_bgrx(rgba, cls.has_alpha)
        cls.reference = rgba if cls.has_alpha else rgba.convert("RGB")
        # a grayscale (R=G=B) variant, to exercise the monochrome lossless path: any standard
        # luma transform is bit-exact when R=G=B, so this still round-trips losslessly:
        gray = rgba.convert("L").convert("RGBA")
        if cls.has_alpha:
            gray.putalpha(rgba.getchannel("A"))
        cls.gray_pixels = cls.pack_bgrx(gray, cls.has_alpha)
        cls.gray_reference = gray if cls.has_alpha else gray.convert("RGB")

    @staticmethod
    def pack_bgrx(rgba_img, has_alpha: bool) -> bytes:
        # pack a PIL RGBA image into BGRA / BGRX order (the canonical xpra screen format):
        raw = rgba_img.tobytes()  # RGBA
        buf = bytearray(len(raw))
        for s in range(0, len(raw), 4):
            buf[s] = raw[s + 2]                                 # B
            buf[s + 1] = raw[s + 1]                             # G
            buf[s + 2] = raw[s]                                 # R
            buf[s + 3] = raw[s + 3] if has_alpha else 0xFF      # A / X
        return bytes(buf)

    def make_image(self, pixels) -> ImageWrapper:
        return ImageWrapper(0, 0, self.width, self.height, pixels, self.src_format, 32,
                            self.stride, 4, planes=ImageWrapper.PACKED, thread_safe=True)

    def decoded_to_image(self, dec_mod, dec_name: str, encoding: str, cdata: bytes, options: typedict):
        # the pillow decoder returns a tuple, the others return an ImageWrapper:
        if dec_name == "dec_pillow":
            rgb_format, raw_data, width, height, rowstride = dec_mod.decompress(encoding, cdata, options)
        else:
            if hasattr(dec_mod, "decompress_to_rgb"):
                img = dec_mod.decompress_to_rgb(cdata, options)
            else:
                img = dec_mod.decompress(cdata, options)
            rgb_format = img.get_pixel_format()
            raw_data = img.get_pixels()
            width, height, rowstride = img.get_width(), img.get_height(), img.get_rowstride()
        # grayscale encoders may report a single-channel "L"/"LA" format; otherwise the data
        # is a packed RGB(X)/BGR(X) variant whose channel count drives the PIL image mode:
        if rgb_format in ("L", "LA"):
            pil_mode = rgb_format
        else:
            pil_mode = "RGBA" if "A" in rgb_format else "RGB"
        # interpret the decoded bytes using the format the decoder reported, then normalise
        # to the canonical channel order so the comparison ignores BGR/RGB/X/A/L differences:
        decoded = Image.frombuffer(pil_mode, (width, height), bytes(raw_data), "raw", rgb_format, rowstride, 1)
        return decoded.convert(self.canon_mode)

    def test_lossless_roundtrip(self):
        tested: list[str] = []
        for enc_name, encoding, dec_name in LOSSLESS_COMBOS:
            enc_mod = loader.load_codec(enc_name)
            dec_mod = loader.load_codec(dec_name)
            if not enc_mod or not dec_mod:
                continue
            if encoding not in tuple(enc_mod.get_encodings()) or encoding not in tuple(dec_mod.get_encodings()):
                continue
            for grayscale in (False, True):
                pixels = self.gray_pixels if grayscale else self.pixels
                reference = self.gray_reference if grayscale else self.reference
                for speed in SPEEDS:
                    with self.subTest(encoder=enc_name, decoder=dec_name, encoding=encoding,
                                      grayscale=grayscale, speed=speed):
                        image = self.make_image(pixels)
                        result = enc_mod.encode(encoding, image, typedict({
                            "quality": QUALITY,
                            "speed": speed,
                            "alpha": self.has_alpha,
                            "grayscale": grayscale,
                            "rgb_format": self.src_format,
                        }))
                        self.assertTrue(result, f"{enc_name} {encoding} returned no data at speed {speed}")
                        cdata = packet_bytes(result[1])
                        self.assertGreater(len(cdata), 0, f"{enc_name} {encoding} produced an empty stream")
                        decoded = self.decoded_to_image(dec_mod, dec_name, encoding, cdata, typedict({
                            "rgb_format": self.src_format,
                            "alpha": self.has_alpha,
                        }))
                        self.assertEqual((decoded.width, decoded.height), (self.width, self.height))
                        diff = ImageChops.difference(decoded, reference)
                        self.assertIsNone(
                            diff.getbbox(),
                            f"{enc_name}->{dec_name} {encoding} grayscale={grayscale} at quality={QUALITY}"
                            f" speed={speed} was not lossless (max per-channel difference: {diff.getextrema()})")
            tested.append(f"{enc_name}->{dec_name}:{encoding}")
        print(f"tested lossless picture round-trip ({self.width}x{self.height}): {tested}")
        if not tested:
            self.skipTest("no lossless picture codec pair available")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
