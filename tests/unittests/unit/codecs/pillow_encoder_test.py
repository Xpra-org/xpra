#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.pillow.encoder import (
    get_encodings, encode,
    get_version, get_type, get_info,
    selftest,
    )


class TestPillow(unittest.TestCase):


    def test_selftest(self):
        for full in (False, True):
            selftest(full)

    def test_module_functions(self):
        assert get_version()>"3"
        assert get_type()=="pillow"
        assert get_info()

    def test_resize(self):
        W = 128
        H = 128
        for speed in (10, 30, 90, 100):
            pixel_data = b"0"*128*128*4
            Bpp = 4
            image = ImageWrapper(0, 0, W, H, pixel_data, "BGRX", 32,
                                 W*Bpp, Bpp, planes=ImageWrapper.PACKED,
                                 thread_safe=True)
            comp = encode("png", image, {
                "speed" : speed,
                "scaled-width" : 64,
                "scaled-height" : 64,
                })
            assert comp

    def test_grayscale(self):
        W = 128
        H = 128
        pixel_data = b"0"*128*128*4
        Bpp = 4
        image = ImageWrapper(0, 0, W, H, pixel_data, "BGRA", 32,
                             W*Bpp, Bpp, planes=ImageWrapper.PACKED,
                             thread_safe=True)
        comp = encode("png", image, {"grayscale"  : True})
        assert comp

    def test_encode_image_formats(self):
        for pixel_format, bpp in {
            "r210"      : 32,
            "BGRA"      : 32,
            "BGR565"    : 16,
            "RLE8"      : 8,
            }.items():
            for encoding in get_encodings():
                if encoding=="jpeg" and pixel_format!="BGRA":
                    continue
                self.do_test_pixel_format(pixel_format, bpp, encoding)

    def do_test_pixel_format(self, pixel_format, bpp, encoding):
        maxsize = 1024*1024*4
        buf = bytearray(maxsize)
        palette = [(10, 255, 127), (0, 0, 0), (255, 255, 255)]
        for transparency in (True, False):
            for quality in (0, 1, 50, 99, 100):
                for speed in (0, 1, 50, 99, 100):
                    for width in (1, 10, 256):
                        for height in (1, 10, 256):
                            size = width*height*bpp
                            pixel_data = bytes(buf[:size])
                            Bpp = bpp//8
                            image = ImageWrapper(0, 0, width, height, pixel_data, pixel_format, 32,
                                                 width*Bpp, Bpp, planes=ImageWrapper.PACKED,
                                                 thread_safe=True, palette=palette)
                            comp = encode(encoding, image, {
                                "quality" : quality,
                                "speed" : speed,
                                "alpha" : transparency,
                                })
                            assert comp

    def test_invalid_pixel_format(self):
        width = 32
        height = 32
        bpp = 4
        pixel_format = "invalid"
        pixel_data = bytes(b"0"*bpp*width*height)
        Bpp = bpp//8
        image = ImageWrapper(0, 0, width, height, pixel_data, pixel_format, 32,
                             width*Bpp, Bpp, planes=ImageWrapper.PACKED,
                             thread_safe=True, palette=None)
        try:
            encode("png", image)
        except Exception:
            pass
        else:
            raise Exception("should not be able to process '%s'" % pixel_format)

    def test_invalid_encoding(self):
        width = 32
        height = 32
        bpp = 4
        pixel_format = "BGRA"
        pixel_data = bytes(b"0"*bpp*width*height)
        Bpp = bpp//8
        image = ImageWrapper(0, 0, width, height, pixel_data, pixel_format, 32,
                             width*Bpp, Bpp, planes=ImageWrapper.PACKED,
                             thread_safe=True, palette=None)
        for encoding in (None, "", True, "hello", 1):
            try:
                encode(encoding, image)
            except Exception:
                pass
            else:
                raise Exception("'%s' is an invalid encoding" % encoding)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
