#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from threading import Lock

from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper


def make_backing(w=100, h=100):
    from xpra.cairo.backing_base import CairoBackingBase

    class TestBacking(CairoBackingBase):
        RGB_MODES = ("BGRA", "BGRX", "BGR", "RGB", "RGBA", "RGBX")

        def _do_paint_rgb(self, *args) -> None:
            self.painted_rgb.append(args)

        def with_gfx_context(self, function, *args) -> None:
            function(None, *args)

        def repaint(self, x, y, w, h) -> None:
            pass

        def update_fps_buffer(self, width, height, pixels) -> None:
            pass

    backing = TestBacking(1, False)
    backing.painted_rgb = []
    backing.border = None
    backing.init(w, h, w, h)
    return backing


class Callbacks(list):

    def __init__(self):
        super().__init__()
        self.results = []
        self.append(lambda success, message="": self.results.append((success, message)))


def rgb_image(w, h, rowstride=0, size=0, pixel_format="BGRX"):
    rowstride = rowstride or w * 4
    return ImageWrapper(0, 0, w, h, (bytes(size or rowstride * h), ), pixel_format, 24, rowstride, 4)


def yuv_image(w, h, planes=3, short=False):
    sizes = (w * h, (w // 2) * (h // 2), (w // 2) * (h // 2))
    pixels = tuple(bytes(size - (1 if short and i == 2 else 0)) for i, size in enumerate(sizes[:planes]))
    strides = (w, w // 2, w // 2)[:planes]
    return ImageWrapper(0, 0, w, h, pixels, "YUV420P", 24, strides, 1, ImageWrapper.PLANAR_3)


class BackingValidationTest(unittest.TestCase):

    def test_rgb_buffer(self):
        backing = make_backing()
        args = (0, 0, 10, 10, 10, 10)
        backing.ui_paint_rgb("rgb", "BGRX", bytes(400), *args, 40, typedict(), Callbacks())
        # rowstride 0 means tightly packed:
        backing.ui_paint_rgb("rgb", "BGRX", bytes(400), *args, 0, typedict(), Callbacks())
        self.assertEqual(len(backing.painted_rgb), 2)
        for rgb_format, size, rowstride in (
            ("BGRX", 399, 40),
            ("BGRX", 400, 36),
            ("RGB", 299, 30),
            ("XYZ", 400, 40),
        ):
            with self.assertRaises(ValueError):
                backing.ui_paint_rgb("rgb", rgb_format, bytes(size), *args, rowstride, typedict(), Callbacks())
        self.assertEqual(len(backing.painted_rgb), 2)

    def test_draw_rgb_validates_decompressed(self):
        from xpra.net import compression
        compression.init_all()
        if "lz4" not in compression.get_enabled_compressors():
            self.skipTest("no lz4")
        backing = make_backing()
        # valid lz4 data, but too short for the update:
        data = compression.get_compressor("lz4")(bytes(100), 1)[1]
        with self.assertRaises(ValueError):
            backing.draw_region(0, 0, 10, 10, "rgb32", data, 40, typedict({"lz4": 1, "rgb_format": "BGRX"}), Callbacks())

    def test_decoded_image(self):
        backing = make_backing()
        # YUV images go through the csc step, which we don't need here:
        backing.video_painted = []
        backing.do_video_paint = lambda *args: backing.video_painted.append(args)
        callbacks = Callbacks()
        backing.paint_image_wrapper("jpeg", rgb_image(10, 10), 0, 0, 10, 10, typedict(), callbacks)
        backing.paint_image_wrapper("jpeg", yuv_image(10, 10), 0, 0, 10, 10, typedict(), callbacks)
        self.assertEqual(len(backing.painted_rgb), 1)
        self.assertEqual(len(backing.video_painted), 1)
        # the image can be the scaled size:
        backing.paint_image_wrapper("jpeg", rgb_image(5, 5), 0, 0, 10, 10, typedict({"scaled_size": (5, 5)}), callbacks)
        for img, options in (
            (rgb_image(10, 9), {}),
            (rgb_image(5, 5), {"scaled_size": (6, 6)}),
            (rgb_image(10, 10, 36), {}),
            (rgb_image(10, 10, size=399), {}),
            (yuv_image(10, 10, 2), {}),
            (yuv_image(10, 10, short=True), {}),
        ):
            with self.assertRaises(ValueError, msg=f"{img} accepted with {options=}"):
                backing.paint_image_wrapper("jpeg", img, 0, 0, 10, 10, typedict(options), callbacks)
            # the image is freed:
            self.assertTrue(img.freed)

    def test_outside(self):
        backing = make_backing()
        for x, y, w, h, outside in (
            (0, 0, 10, 10, False),
            (95, 95, 10, 10, False),
            (-5, -5, 10, 10, False),
            (100, 0, 10, 10, True),
            (0, 100, 10, 10, True),
            (-10, 0, 10, 10, True),
            (0, -10, 10, 10, True),
        ):
            callbacks = Callbacks()
            backing.painted_rgb = []
            backing.draw_region(x, y, w, h, "rgb32", bytes(w * h * 4), w * 4, typedict({"rgb_format": "BGRX"}), callbacks)
            if outside:
                self.assertEqual(backing.painted_rgb, [], f"{w}x{h} at {x},{y} painted")
                self.assertEqual(callbacks.results, [(-1, "outside the backing")])
            else:
                self.assertEqual(len(backing.painted_rgb), 1, f"{w}x{h} at {x},{y} not painted")
        # not before the backing is sized:
        backing.size = (0, 0)
        self.assertFalse(backing.is_outside(200, 200, 10, 10, typedict()))

    def video_backing(self, img):
        backing = make_backing()
        decoded = []

        class FakeDecoder:
            def get_encoding(self):
                return "h264"

            def get_width(self):
                return 10

            def get_height(self):
                return 10

            def get_colorspace(self):
                return "YUV420P"

            def get_type(self):
                return "fake"

            def decompress_image(self, data, options):
                decoded.append(data)
                return img

            def clean(self):
                pass

        backing._decoder_lock = Lock()
        backing._video_decoder = FakeDecoder()
        backing.video_painted = []
        backing.do_video_paint = lambda *args: backing.video_painted.append(args)
        return backing, decoded

    def test_video_outside_is_decoded(self):
        backing, decoded = self.video_backing(yuv_image(10, 10))
        callbacks = Callbacks()
        backing.paint_with_video_decoder("h264", b"frame", 100, 0, 10, 10, typedict({"frame": 1}), callbacks)
        self.assertEqual(decoded, [b"frame"])
        self.assertEqual(backing.video_painted, [])
        self.assertEqual(callbacks.results, [(-1, "outside the backing")])
        # inside:
        backing.paint_with_video_decoder("h264", b"frame", 0, 0, 10, 10, typedict({"frame": 2}), Callbacks())
        self.assertEqual(len(backing.video_painted), 1)

    def test_video_invalid_image(self):
        for img in (yuv_image(10, 8), yuv_image(10, 10, short=True), yuv_image(10, 10, 2), rgb_image(10, 10, size=399)):
            backing, decoded = self.video_backing(img)
            callbacks = Callbacks()
            backing.paint_with_video_decoder("h264", b"frame", 0, 0, 10, 10, typedict({"frame": 1}), callbacks)
            self.assertEqual(backing.video_painted, [])
            self.assertEqual(len(callbacks.results), 1)
            self.assertFalse(callbacks.results[0][0])
            self.assertIn("invalid decoded image", callbacks.results[0][1])
            # the decoder is discarded:
            self.assertIsNone(backing._video_decoder)
            self.assertTrue(img.freed)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
