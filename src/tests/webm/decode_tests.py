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

from PIL import Image
from ctypes import create_string_buffer
from webm import decode
from webm.handlers import BitmapHandler
from webm.tests.common import (IMAGE_WIDTH, IMAGE_HEIGHT, WEBP_IMAGE_DATA,
    DECODE_FILENAME)

try:
    import unittest2 as unittest
except ImportError:
    import unittest


class WebPDecodeTests(unittest.TestCase):
    """
    WebPDecode test cases
    """

    def test_get_info(self):
        """
        Test the GetInfo() method
        """
        result = decode.GetInfo(WEBP_IMAGE_DATA)

        self.assertTrue(isinstance(result, tuple))
        self.assertEqual(len(result), 2)
        self.assertTrue(isinstance(result[0], int))
        self.assertTrue(isinstance(result[1], int))

    def test_get_info_error(self):
        """
        Test the GetInfo() method
        """
        self.assertRaises(Exception, decode.GetInfo, create_string_buffer(0))

    def test_decode_RGB(self):
        """
        Test the DecodeRGB() method
        """
        result = decode.DecodeRGB(WEBP_IMAGE_DATA)
        stride = IMAGE_WIDTH * 3
        size = stride * IMAGE_HEIGHT

        self.assertTrue(isinstance(result, BitmapHandler))
        self.assertEqual(len(result.bitmap), size)
        self.assertEqual(result.format, BitmapHandler.RGB)
        self.assertEqual(result.width, IMAGE_WIDTH)
        self.assertEqual(result.height, IMAGE_HEIGHT)
        self.assertEqual(result.stride, stride)

    def test_decode_RGBA(self):
        """
        Test the DecodeRGBA() method
        """
        result = decode.DecodeRGBA(WEBP_IMAGE_DATA)
        stride = IMAGE_WIDTH * 4
        size = stride * IMAGE_HEIGHT

        self.assertTrue(isinstance(result, BitmapHandler))
        self.assertEqual(len(result.bitmap), size)
        self.assertEqual(result.format, BitmapHandler.RGBA)
        self.assertEqual(result.width, IMAGE_WIDTH)
        self.assertEqual(result.height, IMAGE_HEIGHT)
        self.assertEqual(result.stride, stride)

    def test_decode_BGR(self):
        """
        Test the DecodeBGR() method
        """
        result = decode.DecodeBGR(WEBP_IMAGE_DATA)
        stride = IMAGE_WIDTH * 3
        size = stride * IMAGE_HEIGHT

        self.assertTrue(isinstance(result, BitmapHandler))
        self.assertEqual(len(result.bitmap), size)
        self.assertEqual(result.format, BitmapHandler.BGR)
        self.assertEqual(result.width, IMAGE_WIDTH)
        self.assertEqual(result.height, IMAGE_HEIGHT)
        self.assertEqual(result.stride, stride)

    def test_decode_BGRA(self):
        """
        Test the DecodeBGRA() method
        """
        result = decode.DecodeBGRA(WEBP_IMAGE_DATA)
        stride = IMAGE_WIDTH * 4
        size = stride * IMAGE_HEIGHT

        self.assertTrue(isinstance(result, BitmapHandler))
        self.assertEqual(len(result.bitmap), size)
        self.assertEqual(result.format, BitmapHandler.BGRA)
        self.assertEqual(result.width, IMAGE_WIDTH)
        self.assertEqual(result.height, IMAGE_HEIGHT)
        self.assertEqual(result.stride, stride)

    def test_decode_YUV(self):
        """
        Test the DecodeYUV() method
        """
        result = decode.DecodeYUV(WEBP_IMAGE_DATA)
        size = IMAGE_WIDTH * IMAGE_HEIGHT

        self.assertTrue(isinstance(result, BitmapHandler))
        self.assertEqual(len(result.bitmap), size)
        self.assertEqual(result.format, BitmapHandler.YUV)
        self.assertEqual(result.width, IMAGE_WIDTH)
        self.assertEqual(result.height, IMAGE_HEIGHT)
        self.assertEqual(
            len(result.u_bitmap), int((IMAGE_WIDTH + 1) / 2) * IMAGE_HEIGHT)
        self.assertEqual(
            len(result.v_bitmap), int((IMAGE_WIDTH + 1) / 2) * IMAGE_HEIGHT)
        self.assertEqual(
            result.uv_stride * IMAGE_HEIGHT,
            int((IMAGE_WIDTH + 1) / 2) * IMAGE_HEIGHT
        )

    def test_output_RGB(self):
        """
        Export DecodeRGB() method result to file
        """
        result = decode.DecodeRGB(WEBP_IMAGE_DATA)
        image = Image.frombuffer(
            "RGB", (result.width, result.height), str(result.bitmap),
            "raw", "RGB", 0, 1
        )
        image.save(DECODE_FILENAME.format("RGB"))

    def test_output_RGBA(self):
        """
        Export DecodeRGBA() method result to file
        """
        result = decode.DecodeRGBA(WEBP_IMAGE_DATA)
        image = Image.frombuffer(
            "RGBA", (result.width, result.height), result.bitmap,
            "raw", "RGBA", 0, 1
        )
        image.save(DECODE_FILENAME.format("RGBA"))

    def test_output_BGR(self):
        """
        Export DecodeBGR() method result to file
        """
        result = decode.DecodeBGR(WEBP_IMAGE_DATA)
        image = Image.frombuffer(
            "RGB", (result.width, result.height), str(result.bitmap),
            "raw", "BGR", 0, 1
        )
        image.save(DECODE_FILENAME.format("BGR"))

    def test_output_BGRA(self):
        """
        Export DecodeBGRA() method result to file
        """
        result = decode.DecodeBGRA(WEBP_IMAGE_DATA)
        image = Image.frombuffer(
            "RGBA", (result.width, result.height), str(result.bitmap),
            "raw", "BGRA", 0, 1
        )
        image.save(DECODE_FILENAME.format("BGRA"))
