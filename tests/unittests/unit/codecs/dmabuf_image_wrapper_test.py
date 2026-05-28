#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.codecs.dmabuf.image import DMABufImageWrapper
from xpra.codecs.image import ImageWrapper


class TestDMABufImageWrapper(unittest.TestCase):

    def make_wrapper(self):
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        calls = []

        def download():
            calls.append(True)
            return ImageWrapper(0, 0, 2, 2, b"0123456789abcdef", "BGRA", 32, 8)

        image = DMABufImageWrapper(0, 0, 2, 2, 0x34325241, 0,
                                   (read_fd,), (8,), (0,), download)
        os.close(read_fd)
        return image, calls

    def test_may_download(self):
        image, calls = self.make_wrapper()
        fds = image.fds
        self.assertFalse(image.has_pixels())
        self.assertEqual(image.get_pixels(), b"0123456789abcdef")
        self.assertTrue(image.has_pixels())
        self.assertEqual(len(calls), 1)
        self.assertEqual(image.get_pixel_format(), "BGRA")
        self.assertEqual(image.get_rowstride(), 8)
        self.assertFalse(image.fds)
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)
        self.assertEqual(image.get_pixels(), b"0123456789abcdef")
        self.assertEqual(len(calls), 1)
        image.free()

    def test_sub_image_downloads(self):
        image, calls = self.make_wrapper()
        sub = image.get_sub_image(0, 0, 1, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sub.get_pixels(), b"0123")
        image.free()

    def test_free_closes_fds(self):
        image, _calls = self.make_wrapper()
        fds = image.fds
        self.assertTrue(fds)
        image.free()
        image.free()
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
