# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import weakref
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import xpra
from xpra.codecs.constants import CodecStateException


# The wrapper itself is pure Python; load it without the Windows package initializer.
spec = spec_from_file_location("d3d11_image_wrapper", Path(xpra.__file__).parent / "platform/win32/d3d11/image.py")
image_module = module_from_spec(spec)
spec.loader.exec_module(image_module)
DXGIImageWrapper = image_module.DXGIImageWrapper


class FakeCapture:

    def __init__(self):
        self.closed = False
        self.downloads = []
        self.frame = 0

    def download(self, x, y, width, height):
        if self.closed:
            raise CodecStateException("capture closed")
        self.downloads.append((x, y, width, height))
        return bytes((self.frame,)) * (width * height * 4)


class TestDXGIImageWrapper(unittest.TestCase):

    def make_image(self, capture):
        return DXGIImageWrapper(2, 1, 4, 2, "BGRX", 32, capture)

    def test_freeze_downloads_once_and_keeps_the_frame(self):
        capture = FakeCapture()
        image = self.make_image(capture)
        self.assertIsNone(image.get_gpu_buffer())
        self.assertFalse(image.has_pixels())
        self.assertTrue(image.freeze())
        capture.frame = 1
        self.assertEqual(image.get_pixels(), bytes(32))
        self.assertEqual(capture.downloads, [(2, 1, 4, 2)])
        self.assertIsNone(image.get_gpu_buffer())
        image.free()

    def test_keeps_capture_alive_until_freed(self):
        capture = FakeCapture()
        ref = weakref.ref(capture)
        image = self.make_image(capture)
        del capture
        self.assertIsNotNone(ref())
        self.assertEqual(image.get_pixels(), bytes(32))
        image.free()
        image.free()
        self.assertIsNone(ref())
        self.assertFalse(image.get_pixels())

    def test_capture_cleaned_before_download(self):
        capture = FakeCapture()
        image = self.make_image(capture)
        capture.closed = True
        with self.assertRaises(CodecStateException):
            image.get_pixels()
        self.assertFalse(image.has_pixels())
        image.free()

    def test_sub_image_and_restride_download_pixels(self):
        capture = FakeCapture()
        image = self.make_image(capture)
        image.set_target_x(20)
        image.set_target_y(10)
        image.set_full_range(False)
        sub = image.get_sub_image(1, 1, 2, 1)
        self.assertEqual(sub.get_pixels(), bytes(8))
        self.assertEqual((sub.get_target_x(), sub.get_target_y()), (21, 11))
        self.assertFalse(sub.get_full_range())
        self.assertTrue(image.restride(20))
        self.assertEqual(len(image.get_pixels()), 40)
        self.assertEqual(capture.downloads, [(2, 1, 4, 2)])
        image.free()
        sub.free()


if __name__ == "__main__":
    unittest.main()
