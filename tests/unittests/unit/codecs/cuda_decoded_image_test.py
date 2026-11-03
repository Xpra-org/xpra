#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.codecs.image import ImageWrapper

try:
    from xpra.codecs.nvidia.cuda.decoded_image import CUDADecodedImageWrapper
except ImportError:
    CUDADecodedImageWrapper = None


@unittest.skipIf(CUDADecodedImageWrapper is None, "NVIDIA CUDA decoded image module is not available")
class TestCUDADecodedImage(unittest.TestCase):

    def make_image(self, nplanes=0):
        device = Mock()
        context = Mock()
        planes = tuple(memoryview(bytearray(b"0123456789abcdef")) for _ in range(nplanes or 1))
        downloader = Mock(return_value=planes)
        image = CUDADecodedImageWrapper(0, 0, 2, 2, (), "NV12" if nplanes else "RGBX", 24,
                                        (8,) * nplanes if nplanes else 8, 4, nplanes,
                                        gpu_buffer=device, downloader=downloader, cuda_context=context)
        return image, device, context, downloader, planes

    def test_lazy_download(self):
        for nplanes in (0, 2):
            image, device, context, downloader, planes = self.make_image(nplanes)
            self.assertEqual(image.pixels, ())
            self.assertFalse(image.has_pixels())
            self.assertIs(image.get_gpu_buffer(), device)
            downloader.assert_not_called()
            self.assertIs(image.get_plane(0), planes[0])
            for i, plane in enumerate(planes):
                self.assertIs(image.get_plane(i), plane)
            downloader.assert_called_once_with(device)
            device.free.assert_called_once_with()
            self.assertIsNone(image.get_gpu_buffer())
            self.assertEqual(context.push.call_count, context.pop.call_count)
            image.clone_pixel_data()
            self.assertIsInstance(image.get_plane(0), bytes)
            image.free()
            image.free()
            device.free.assert_called_once_with()
            with self.assertRaises(RuntimeError):
                image.get_plane(0)

    def test_free_without_download(self):
        image, device, context, downloader, _ = self.make_image()
        image.free()
        image.free()
        downloader.assert_not_called()
        device.free.assert_called_once_with()
        self.assertEqual(context.push.call_count, context.pop.call_count)

    def test_failed_download_keeps_device_for_cleanup(self):
        image, device, context, downloader, _ = self.make_image()
        downloader.side_effect = RuntimeError("download failed")
        with self.assertRaisesRegex(RuntimeError, "download failed"):
            image.get_plane(0)
        self.assertEqual(image.pixels, ())
        self.assertIs(image.get_gpu_buffer(), device)
        self.assertEqual(context.push.call_count, context.pop.call_count)
        image.free()
        device.free.assert_called_once_with()

    def test_packed_subimage(self):
        image, device, _, downloader, _ = self.make_image()
        sub = image.get_sub_image(0, 1, 1, 1)
        self.assertEqual(sub.get_plane(0), b"89ab")
        self.assertEqual(sub.get_planes(), ImageWrapper.PACKED)
        downloader.assert_called_once_with(device)


if __name__ == "__main__":
    unittest.main()
