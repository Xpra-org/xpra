#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest
from xpra.codecs.image_wrapper import ImageWrapper

class TestImageWrapper(unittest.TestCase):

    def test_sub_image(self):
        W = 1920
        H = 1080
        buf = bytearray(W*H*4)
        #set the first N pixels of each line to 1:
        SET_X = 2
        for x in range(SET_X):
            for y in range(H):
                #4 bytes per pixel:
                for i in range(4):
                    buf[y*(W*4) + x*4 + i] = 1
        img = ImageWrapper(0, 0, W, H, buf, "RGBX", 24, W*4, planes=ImageWrapper.PACKED, thread_safe=True)
        #print("image pixels head=%s" % (binascii.hexlify(img.get_pixels()[:128]), ))
        for x in range(3):
            SW, SH = 6, 6
            sub = img.get_sub_image(x, 0, SW, SH)
            #print("%s.get_sub_image%s=%s" % (img, (x, 0, SW, SH), sub))
            assert sub.get_rowstride()==(SW*4)
            sub_buf = sub.get_pixels()
            #print("pixels for %ix%i: %i" % (SW, SH, len(sub_buf)))
            #print("pixels=%s" % (binascii.hexlify(sub_buf), ))
            #verify that the pixels are set to 1 / 0:
            v = int(x<SET_X)
            for y in range(SH):
                for i in range(4):
                    try:
                        av = ord(sub_buf[y*(SW*4)+i])
                    except:
                        #python3:
                        av = sub_buf[y*(SW*4)+i]
                    assert av==v, "expected value %#x for pixel (0, %i) of sub-image %s at (%i, 0), but got %#x" % (v, y, sub, x, av)
        start = time.time()
        copy = img.get_sub_image(0, 0, W, H)
        end = time.time()
        print("image wrapper full %ix%i copy speed: %iMB/s" % (W, H, (W*4*H)/(end-start)/1024/1024))
        assert copy.get_pixels()==img.get_pixels()
        total = 0
        N = 10
        region = (W//4, H//4, W//2, H//2)
        for _ in range(N):
            start = time.time()
            copy = img.get_sub_image(*region)
            end = time.time()
            total += end-start
        print("image wrapper sub image %ix%i copy speed: %iMB/s" % (W//2, H//2, (W//2*4*H//2)/total/1024/1024))


def main():
    unittest.main()

if __name__ == '__main__':
    main()
