#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import BytesIO

from xpra.codecs.image import ImageWrapper
from xpra.server.shadow.root_window_model import CaptureWindowModel

W = 8
H = 4
# one blue BGRX pixel, and the row padding that captures may add:
BLUE = b"\xff\x00\x00\x00"
PADDING = 16


def make_image(x: int, y: int, w: int, h: int) -> ImageWrapper:
    stride = w * 4 + PADDING
    pixels = (BLUE * w + b"\x77" * PADDING) * h
    return ImageWrapper(x, y, w, h, pixels, "BGRX", 24, stride, 4, ImageWrapper.PACKED, True)


class GPUImageWrapper(ImageWrapper):
    """ like the DXGI and CUDA wrappers: the pixels are only downloaded on demand """

    def __init__(self, x: int, y: int, w: int, h: int):
        super().__init__(x, y, w, h, None, "BGRX", 24, w * 4 + PADDING, 4, ImageWrapper.PACKED, True)

    def get_pixels(self):
        if self.pixels is None:
            self.pixels = make_image(self.x, self.y, self.width, self.height).get_pixels()
        return super().get_pixels()


class FakeCapture:
    """ a capture without a `take_screenshot()` method, ie: DXGI or NvFBC """

    def __init__(self, image_class=None):
        self.image_class = image_class
        self.requests = []
        self.images = []

    def get_image(self, x: int, y: int, w: int, h: int):
        self.requests.append((x, y, w, h))
        if not self.image_class:
            return None
        image = self.image_class(x, y, w, h)
        self.images.append(image)
        return image


class ScreenshotCapture(FakeCapture):

    @staticmethod
    def take_screenshot():
        return 1, 1, "png", 0, b"screenshot"


class CaptureWindowModelScreenshotTest(unittest.TestCase):

    def decode(self, data: bytes):
        from PIL import Image
        img = Image.open(BytesIO(data))
        img.load()
        return img

    def test_uses_the_capture_screenshot(self):
        capture = ScreenshotCapture()
        rwm = CaptureWindowModel(capture, geometry=(0, 0, W, H))
        self.assertEqual(rwm.take_screenshot(), (1, 1, "png", 0, b"screenshot"))
        self.assertEqual(capture.requests, [])

    def test_encodes_the_model_area(self):
        for image_class in (make_image, GPUImageWrapper):
            with self.subTest(image_class=image_class.__name__):
                capture = FakeCapture(image_class)
                rwm = CaptureWindowModel(capture, geometry=(100, 50, W, H))
                w, h, encoding, _rowstride, data = rwm.take_screenshot()
                self.assertEqual((w, h, encoding), (W, H, "png"))
                # the base model works in global coordinates:
                self.assertEqual(capture.requests, [(100, 50, W, H)])
                img = self.decode(data)
                self.assertEqual(img.size, (W, H))
                # the row padding must not leak into the picture:
                self.assertEqual(img.convert("RGB").getcolors(), [(W * H, (0, 0, 255))])
                self.assertTrue(capture.images[0].freed)

    def test_no_image(self):
        capture = FakeCapture()
        rwm = CaptureWindowModel(capture, geometry=(0, 0, W, H))
        self.assertIsNone(rwm.take_screenshot())


class ShadowDisplayScreenshotTest(unittest.TestCase):

    def make_display(self, capture):
        from xpra.server.shadow.display import ShadowDisplayMixin
        rwm = CaptureWindowModel(capture, geometry=(0, 0, W, H))
        window = type("FakeWindowSubsystem", (), {"models": lambda _self: [rwm]})()
        display = ShadowDisplayMixin()
        display.get_subsystem = lambda _name: window
        return display

    def test_screenshot_packet(self):
        display = self.make_display(FakeCapture(make_image))
        packet = display.do_make_screenshot_packet()
        self.assertEqual(packet[1:4], (W, H, "png"))

    def test_no_screenshot(self):
        display = self.make_display(FakeCapture())
        self.assertIsNone(display.do_make_screenshot_packet())


def main():
    unittest.main()


if __name__ == '__main__':
    main()
