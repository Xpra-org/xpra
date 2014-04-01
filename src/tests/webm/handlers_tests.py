# -*- coding: utf-8 -*-
"""
Copyright (c) 2011, Daniele Esposti <expo@expobrain.net>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * The name of the contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

from webm.handlers import WebPHandler, BitmapHandler
from webm.tests.common import (IMAGE_WIDTH, IMAGE_HEIGHT, WEBP_IMAGE_DATA,
    WEBP_IMAGE_FILE)
import os

try:
    import unittest2 as unittest
except ImportError:
    import unittest


class BitmapHandlerTests(unittest.TestCase):
    """
    BitmapHandler tests cases
    """

    def test_image_types_enum(self):
        """
        Test image types enumerator
        """
        self.assertEqual(BitmapHandler.RGB, 0)
        self.assertEqual(BitmapHandler.RGBA, 1)
        self.assertEqual(BitmapHandler.BGR, 2)
        self.assertEqual(BitmapHandler.BGRA, 3)
        self.assertEqual(BitmapHandler.YUV, 4)

    def test_is_valid(self):
        """
        Test is_valid() property
        """
        # Invalid
        self.assertFalse(
            BitmapHandler(None, None, IMAGE_WIDTH, IMAGE_HEIGHT, -1).is_valid)
        self.assertFalse(BitmapHandler(None, None, -1, -1, -1).is_valid)
        self.assertFalse(
            BitmapHandler(None, BitmapHandler.YUV, 0, 0, None).is_valid)

        # Valid
        image = BitmapHandler(
            WEBP_IMAGE_DATA, BitmapHandler.RGB,
            IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH * 3
        )

        self.assertTrue(image.is_valid)
        self.assertEqual(image.bitmap, WEBP_IMAGE_DATA)
        self.assertEqual(image.format, BitmapHandler.RGB)
        self.assertEqual(image.width, IMAGE_WIDTH)
        self.assertEqual(image.height, IMAGE_HEIGHT)

    def test_is_valid_yuv(self):
        """
        Test is_valid() property for YUV format
        """
        # Create fake Y and UV bitmaps
        bitmap = bytearray(IMAGE_WIDTH * IMAGE_HEIGHT)
        uv_bitmap = bytearray(int(IMAGE_WIDTH * IMAGE_HEIGHT / 2))

        # Create image instance
        image = BitmapHandler(
            bitmap, BitmapHandler.YUV, IMAGE_WIDTH, IMAGE_HEIGHT,
            u_bitmap=uv_bitmap, v_bitmap=uv_bitmap,
            stride=IMAGE_WIDTH, uv_stride=int(IMAGE_WIDTH / 2)
        )

        self.assertTrue(image.is_valid)
        self.assertEqual(image.bitmap, bitmap)
        self.assertEqual(image.format, BitmapHandler.YUV)
        self.assertEqual(image.width, IMAGE_WIDTH)
        self.assertEqual(image.height, IMAGE_HEIGHT)
        self.assertEqual(image.u_bitmap, uv_bitmap)
        self.assertEqual(image.v_bitmap, uv_bitmap)
        self.assertEqual(image.stride, IMAGE_WIDTH)
        self.assertEqual(image.uv_stride, int(IMAGE_WIDTH / 2))


class WebPHandlerTests(unittest.TestCase):
    """
    WebPHandler test cases
    """

    TEST_IMAGE_FILE = os.path.join(os.path.dirname(__file__),
                                   "webphandler_{0}.webp")

    def test_load_by_filename(self):
        """
        Test loading a .webp file
        """
        image = WebPHandler.from_file(WEBP_IMAGE_FILE)

        self.assertTrue(isinstance(image, WebPHandler))
        self.assertTrue(image.is_valid)
        self.assertEqual(image.width, IMAGE_WIDTH)
        self.assertEqual(image.height, IMAGE_HEIGHT)
        self.assertTrue(isinstance(image.data, bytearray))
