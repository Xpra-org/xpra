#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
import unittest
import zlib
from unittest.mock import patch

from xpra.codecs.image import ImageWrapper
from xpra.net.rfb.const import RFBEncoding
from xpra.net.rfb import encode


def image(pixels: bytes, width=2, height=1, pixel_format="BGRX", rowstride=None):
    return ImageWrapper(0, 0, width, height, pixels, pixel_format, 24,
                        rowstride or width * len(pixel_format), len(pixel_format))


class RFBEncodeTest(unittest.TestCase):

    def test_header_and_tight_lengths(self):
        header = encode.make_header(RFBEncoding.RAW, 1, 2, 3, 4)
        self.assertEqual(header, struct.pack("!BBHHHHHi", 0, 0, 1, 1, 2, 3, 4, RFBEncoding.RAW))
        for length, suffix_size in ((0, 2), (127, 2), (128, 3), (16382, 3), (16383, 4), (4_194_302, 4)):
            with self.subTest(length=length):
                self.assertEqual(len(encode.tight_header(RFBEncoding.TIGHT, 0, 0, 1, 1, 0x90, length)),
                                 len(encode.make_header(RFBEncoding.TIGHT, 0, 0, 1, 1)) + suffix_size)
        with self.assertRaises(AssertionError):
            encode.tight_header(RFBEncoding.TIGHT, 0, 0, 1, 1, 0, 4_194_303)

    def test_raw_pixels_and_rowstride(self):
        self.assertEqual(encode.raw_pixels(None), b"")
        pixels = b"abcdefghPAD!ijklmnopPAD!"
        img = image(pixels, width=2, height=2, rowstride=12)
        self.assertEqual(encode.raw_pixels(img), b"abcdefghijklmnop")
        header, data = encode.raw_encode_image(image(b"12345678"), 2, 3, 2, 1)
        self.assertEqual(data, b"12345678")
        self.assertEqual(len(header), 16)

    def test_zlib_stream_continuity(self):
        compressor = zlib.compressobj(1)
        decompressor = zlib.decompressobj()
        outputs = []
        for pixels in (b"12345678", b"abcdefgh"):
            header, data = encode.zlib_encode_image(image(pixels), 0, 0, 2, 1, compressor)
            self.assertEqual(struct.unpack("!I", header[-4:])[0], len(data))
            outputs.append(decompressor.decompress(data))
        self.assertEqual(outputs, [b"12345678", b"abcdefgh"])
        self.assertEqual(encode.zlib_encode_image(None, 0, 0, 1, 1), [])

    def test_tight_and_rgb222_failures(self):
        self.assertEqual(encode.tight_encode_image(None, 0, 0, 1, 1), [])
        self.assertEqual(encode.tight_png_image(None, 0, 0, 1, 1), [])
        self.assertEqual(encode.rgb222_encode_image(image(b"123", 1, 1, "RGB"), 0, 0, 1, 1), [])
        with patch.object(encode, "pillow_encode", return_value=b"encoded") as pillow:
            header, data = encode.tight_encode_image(image(b"12345678"), 0, 0, 2, 1, 75, 25)
            self.assertEqual(data, b"encoded")
            self.assertEqual(header[16], 0x90)
            pillow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
