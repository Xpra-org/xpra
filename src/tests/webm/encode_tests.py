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
from webm import encode
from webm.handlers import BitmapHandler, WebPHandler
from webm.tests.common import (IMAGE_WIDTH, IMAGE_HEIGHT, PNG_BITMAP_DATA,
    ENCODE_FILENAME)

try:
    import unittest2 as unittest
except ImportError:
    import unittest


class WebPEncodeTests(unittest.TestCase):
    """
    WebPEncode test cases
    """

    def test_encode_RGB(self):
        """
        Test the EncodeRGB() method
        """
        image = BitmapHandler(
            PNG_BITMAP_DATA, BitmapHandler.RGB,
            IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH * 3
        )
        result = encode.EncodeRGB(image)

        self.assertTrue(isinstance(result, WebPHandler))
        self.assertEqual(result.width, IMAGE_WIDTH)
        self.assertEqual(result.height, IMAGE_HEIGHT)

    def test_encode_RGBA(self):
        """
        Test the EncodeRGBA() method
        """
        # Convert to RGBA
        size = IMAGE_WIDTH * IMAGE_HEIGHT
        bitmap = bytearray(size * 4)

        for i in xrange(size):
            bitmap[ i * 4 ] = PNG_BITMAP_DATA[ i * 3 ]
            bitmap[ i * 4 + 1 ] = PNG_BITMAP_DATA[ i * 3 + 1 ]
            bitmap[ i * 4 + 2 ] = PNG_BITMAP_DATA[ i * 3 + 2 ]

        image = BitmapHandler(
            bitmap, BitmapHandler.RGBA,
            IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH * 4
        )

        # Encode image
        result = encode.EncodeRGB(image)

        self.assertTrue(isinstance(result, WebPHandler))
        self.assertEqual(result.width, IMAGE_WIDTH)
        self.assertEqual(result.height, IMAGE_HEIGHT)

    def test_encode_BGRA(self):
        """
        Test the EncodeBGRA() method
        """
        # Convert to RGBA
        size = IMAGE_WIDTH * IMAGE_HEIGHT
        bitmap = bytearray(size * 4)

        for i in xrange(size):
            bitmap[ i * 4 ] = PNG_BITMAP_DATA[ i * 3 + 2 ]
            bitmap[ i * 4 + 1 ] = PNG_BITMAP_DATA[ i * 3 + 1 ]
            bitmap[ i * 4 + 2 ] = PNG_BITMAP_DATA[ i * 3 ]

        image = BitmapHandler(
            bitmap, BitmapHandler.BGRA,
            IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH * 4
        )

        # Encode image
        result = encode.EncodeBGRA(image)

        self.assertTrue(isinstance(result, WebPHandler))
        self.assertEqual(result.width, IMAGE_WIDTH)
        self.assertEqual(result.height, IMAGE_HEIGHT)

    def test_encode_BGR(self):
        """
        Test the EncodeBGR() method
        """
        # Convert to RGBA
        size = IMAGE_WIDTH * IMAGE_HEIGHT
        bitmap = bytearray(size * 4)

        for i in xrange(size):
            bitmap[ i * 4 ] = PNG_BITMAP_DATA[ i * 3 + 2 ]
            bitmap[ i * 4 + 1 ] = PNG_BITMAP_DATA[ i * 3 + 1 ]
            bitmap[ i * 4 + 2 ] = PNG_BITMAP_DATA[ i * 3 ]

        image = BitmapHandler(
            bitmap, BitmapHandler.BGRA,
            IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH * 4
        )

        # Encode image
        result = encode.EncodeBGRA(image)

        self.assertTrue(isinstance(result, WebPHandler))
        self.assertEqual(result.width, IMAGE_WIDTH)
        self.assertEqual(result.height, IMAGE_HEIGHT)

    def test_output_RGB(self):
        """
        Export EncodeRGB() method result to file
        """
        image = BitmapHandler(
            PNG_BITMAP_DATA, BitmapHandler.RGB,
            IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH * 3
        )
        result = encode.EncodeRGB(image)

        file(ENCODE_FILENAME.format("RGB"), "wb").write(result.data)

    def test_output_RGBA(self):
        """
        Export EncodeRGBA() method result to file
        """
        # Convert to RGBA
        size = IMAGE_WIDTH * IMAGE_HEIGHT
        bitmap = bytearray(size * 4)

        for i in xrange(size):
            bitmap[ i * 4 ] = PNG_BITMAP_DATA[ i * 3 ]
            bitmap[ i * 4 + 1 ] = PNG_BITMAP_DATA[ i * 3 + 1 ]
            bitmap[ i * 4 + 2 ] = PNG_BITMAP_DATA[ i * 3 + 2 ]

        image = BitmapHandler(
            bitmap, BitmapHandler.RGBA,
            IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH * 4
        )

        # Save image
        result = encode.EncodeRGBA(image)

        file(ENCODE_FILENAME.format("RGBA"), "wb").write(result.data)

    def test_output_BGRA(self):
        """
        Export EncodeBGRA() method result to file
        """
        # Convert to RGBA
        size = IMAGE_WIDTH * IMAGE_HEIGHT
        bitmap = bytearray(size * 4)

        for i in xrange(size):
            bitmap[ i * 4 ] = PNG_BITMAP_DATA[ i * 3 + 2 ]
            bitmap[ i * 4 + 1 ] = PNG_BITMAP_DATA[ i * 3 + 1 ]
            bitmap[ i * 4 + 2 ] = PNG_BITMAP_DATA[ i * 3 ]

        image = BitmapHandler(
            bitmap, BitmapHandler.BGRA,
            IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH * 4
        )

        # Save image
        result = encode.EncodeBGRA(image)

        file(ENCODE_FILENAME.format("BGRA"), "wb").write(result.data)

    def test_output_BGR(self):
        """
        Export EncodeBGR() method result to file
        """
        # Convert to RGBA
        size = IMAGE_WIDTH * IMAGE_HEIGHT
        bitmap = bytearray(size * 3)

        for i in xrange(size):
            bitmap[ i * 3 ] = PNG_BITMAP_DATA[ i * 3 + 2 ]
            bitmap[ i * 3 + 1 ] = PNG_BITMAP_DATA[ i * 3 + 1 ]
            bitmap[ i * 3 + 2 ] = PNG_BITMAP_DATA[ i * 3 ]

        image = BitmapHandler(
            bitmap, BitmapHandler.BGR,
            IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH * 3
        )

        # Save image
        result = encode.EncodeBGR(image)

        file(ENCODE_FILENAME.format("BGR"), "wb").write(result.data)
