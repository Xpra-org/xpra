#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016, 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.util import envbool
from xpra.os_util import monotonic_time

SHOW_PERF = envbool("XPRA_SHOW_PERF")


class TestImageWrapper(unittest.TestCase):

    def test_sub_image(self):
        X = 0
        Y = 0
        W = 640
        H = 480
        D = 24
        buf = bytearray(W*H*4)
        #the pixel value is derived from the sum of its coordinates (modulo 256)
        for x in range(W):
            for y in range(H):
                #4 bytes per pixel:
                for i in range(4):
                    buf[y*(W*4) + x*4 + i] = (x+y) % 256
        img = ImageWrapper(X, Y, W, H, buf, "RGBX", D, W*4, planes=ImageWrapper.PACKED, thread_safe=True)
        #verify attributes:
        assert img.get_x()==X
        assert img.get_y()==Y
        assert img.get_width()==W
        assert img.get_height()==H
        assert img.get_depth()==D
        assert img.get_bytesperpixel()==4
        assert img.get_rowstride()==W*4
        assert img.get_size()==W*4*H
        assert img.has_pixels()
        #print("image pixels head=%s" % (binascii.hexlify(img.get_pixels()[:128]), ))
        for x in range(3):
            SW, SH = 6, 6
            sub = img.get_sub_image(x, 0, SW, SH)
            #print("%s.get_sub_image%s=%s" % (img, (x, 0, SW, SH), sub))
            #this is only true for the pure python ImageWrapper:
            #(the X11 image wrapper references the same underlying XShm pixels, with the same rowstride)
            assert sub.get_rowstride()==(SW*4)
            sub_buf = sub.get_pixels()
            #print("pixels for %ix%i: %i" % (SW, SH, len(sub_buf)))
            #print("pixels=%s" % (binascii.hexlify(sub_buf), ))
            #verify that the pixels are set to 1 / 0:
            for y in range(SH):
                v = (x+y)%256
                for i in range(4):
                    av = sub_buf[y*(SW*4)+i]
                    if av!=v:
                        raise Exception("""expected value %#x for pixel (0, %i)
                                        of sub-image %s at (%i, 0), but got %#x""" % (v, y, sub, x, av))
        start = monotonic_time()
        copy = img.get_sub_image(0, 0, W, H)
        end = monotonic_time()
        if SHOW_PERF:
            print("image wrapper full %ix%i copy speed: %iMB/s" % (W, H, (W*4*H)/(end-start)/1024/1024))
        assert copy.get_pixels()==img.get_pixels()
        total = 0
        N = 10
        for i in range(N):
            region = (W//4-N//2+i, H//4-N//2+i, W//2, H//2)
            start = monotonic_time()
            copy = img.get_sub_image(*region)
            end = monotonic_time()
            total += end-start
        if SHOW_PERF:
            print("image wrapper sub image %ix%i copy speed: %iMB/s" % (W//2, H//2, N*(W//2*4*H//2)/total/1024/1024))
        #invalid sub-image should fail:
        for x, y, w, h in (
            (-1, 0, 1, 1),
            (0, -1, 1, 1),
            (0, 0, 0, 1),
            (0, 0, 1, 0),
            (1, 0, W, 1),
            (0, 1, 1, H),
            ):
            try:
                img.get_sub_image(x, y, w, h)
            except Exception:
                pass
            else:
                raise Exception("sub image of %s with coords %s should have failed" % (img, (x, y, w, h)))
        #freeze is a no-op in the default wrapper:
        assert img.freeze() is False
        img.clone_pixel_data()

    def test_restride(self):
        #restride of planar is not supported:
        img = ImageWrapper(0, 0, 1, 1, ["0", "0", "0"], "YUV420P", 24, 1, planes=ImageWrapper.PLANAR_3, thread_safe=True)
        assert img.restride(1) is False


def main():
    unittest.main()

if __name__ == '__main__':
    main()
