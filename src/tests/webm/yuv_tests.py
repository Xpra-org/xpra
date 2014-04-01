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
from webm import yuv, decode
from webm.tests.common import WEBP_IMAGE_DATA, DECODE_FILENAME

try:
    import unittest2 as unittest
except ImportError:
    import unittest


class YuvTests(unittest.TestCase):
    """
    YUV to RGB conversion module test case
    """

    def test_init(self):
        """
        Test intialise lookup tables
        """
        import webm.yuv as yuv

        self.assertEqual(len(yuv.VP8kVToR), 256)
        self.assertEqual(len(yuv.VP8kUToB), 256)
        self.assertEqual(len(yuv.VP8kVToG), 256)
        self.assertEqual(len(yuv.VP8kUToG), 256)
        self.assertEqual(
            len(yuv.VP8kClip), yuv.YUV_RANGE_MAX - yuv.YUV_RANGE_MIN)

        self.assertNotEqual(yuv.VP8kVToR, [0] * 256)
        self.assertNotEqual(yuv.VP8kUToB, [0] * 256)
        self.assertNotEqual(yuv.VP8kVToG, [0] * 256)
        self.assertNotEqual(yuv.VP8kUToG, [0] * 256)
        self.assertNotEqual(
            yuv.VP8kClip, [0] * (yuv.YUV_RANGE_MAX - yuv.YUV_RANGE_MIN))

    def test_output_YUV_to_RGB(self):
        """
        Export DecodeYUV() method result to a RGB file
        """
        # Get YUV data and convert to RGB
        result = decode.DecodeYUV(WEBP_IMAGE_DATA)
        result = yuv.YUVtoRGB(result)

        # Save image
        image = Image.frombuffer(
            "RGB", (result.width, result.height), str(result.bitmap),
            "raw", "RGB", 0, 1
        )
        image.save(DECODE_FILENAME.format("YUV_RGB"))

    def test_output_YUV_to_RGBA(self):
        """
        Export DecodeYUV() method result to a RGBA file
        """
        # Get YUV data and convert to RGB
        result = decode.DecodeYUV(WEBP_IMAGE_DATA)
        result = yuv.YUVtoRGBA(result)

        # Save image
        image = Image.frombuffer(
            "RGBA", (result.width, result.height), str(result.bitmap),
            "raw", "RGBA", 0, 1
        )
        image.save(DECODE_FILENAME.format("YUV_RGBA"))

    def test_output_YUV_to_BGR(self):
        """
        Export DecodeYUV() method result to a BGR file
        """
        # Get YUV data and convert to BGR
        result = decode.DecodeYUV(WEBP_IMAGE_DATA)
        result = yuv.YUVtoBGR(result)

        # Save image
        image = Image.frombuffer(
            "RGB", (result.width, result.height), str(result.bitmap),
            "raw", "BGR", 0, 1
        )
        image.save(DECODE_FILENAME.format("YUV_BGR"))

    def test_output_YUV_to_BGRA(self):
        """
        Export DecodeYUV() method result to a BGRA file
        """
        # Get YUV data and convert to BGRA
        result = decode.DecodeYUV(WEBP_IMAGE_DATA)
        result = yuv.YUVtoBGRA(result)

        # Save image
        image = Image.frombuffer(
            "RGBA", (result.width, result.height), str(result.bitmap),
            "raw", "BGRA", 0, 1
        )
        image.save(DECODE_FILENAME.format("YUV_BGRA"))
