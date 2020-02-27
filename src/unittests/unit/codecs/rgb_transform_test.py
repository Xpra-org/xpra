#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016, 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.rgb_transform import rgb_reformat

X = 0
Y = 0
W = 640
H = 480
D = 24

class RGBTransformTest(unittest.TestCase):

    def make_test_image(self, fmt, buf):
        stride = W*4
        if fmt=="BGR565":
            stride = W*2
        len = stride*H
        return ImageWrapper(X, Y, W, H, bytes(buf[:len]), fmt, D, stride, planes=ImageWrapper.PACKED)

    def test_rgb_reformat(self):
        buf = bytearray(W*H*4)
        for from_fmt, to_fmts in {
            "BGRA"  : ("RGB", "RGBX", "RGBA"),
            "BGRX"  : ("RGB", "RGBX",),
            "r210"  : ("RGBA", "RGBX", "RGB"),
            "BGR565": ("RGBA", "RGBX", "RGB"),
            }.items():
            for to_fmt in to_fmts:
                img = self.make_test_image(from_fmt, buf)
                transparency = to_fmt.find("A")>=0
                r = rgb_reformat(img, to_fmt, transparency)
                #print("%s to %s (transparency=%s)" % (from_fmt, to_fmt, transparency))
                assert r is True, "rgb_reformat%s=%s" % ((img, to_fmt, transparency), r)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
