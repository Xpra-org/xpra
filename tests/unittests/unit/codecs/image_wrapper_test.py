#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import monotonic

from xpra.codecs.image import ImageWrapper
from xpra.util.env import envbool

SHOW_PERF = envbool("XPRA_SHOW_PERF")


class TestImageWrapper(unittest.TestCase):

    def test_plane_buffers(self):
        from collections.abc import Buffer
        from xpra.buffers.membuf import get_membuf
        for nplanes in (0, 2, 3, 4):
            for factory in (bytes, bytearray, memoryview, lambda data: get_membuf(len(data), False)):
                with self.subTest(planes=nplanes, buffer=factory):
                    planes = [factory(b"0123456789abcdef") for _ in range(nplanes or 1)]
                    image = ImageWrapper(0, 0, 2, 2, planes, "RGBX" if not nplanes else "YUV420P", 24,
                                         8 if not nplanes else (8,) * nplanes, planes=nplanes)
                    self.assertIs(image.pixels, planes)
                    for i, plane in enumerate(planes):
                        self.assertIsInstance(image.get_plane(i), Buffer)
                        self.assertIs(image.get_plane(i), plane)
                    if nplanes:
                        with self.assertRaises(ValueError):
                            image.get_pixels()
                    else:
                        self.assertIs(image.get_pixels(), planes[0])
                    expected = tuple(memoryview(plane).tobytes() for plane in planes)
                    image.clone_pixel_data()
                    self.assertIsNot(image.pixels, planes)
                    self.assertEqual(tuple(image.pixels), expected)
                    if isinstance(planes[0], bytearray):
                        planes[0][0] ^= 0xff
                        self.assertEqual(image.get_plane(0), expected[0])
                    replacement = tuple(bytearray(plane) for plane in expected)
                    image.set_pixels(replacement)
                    self.assertIs(image.pixels, replacement)
                    image.free()
                    self.assertEqual(image.pixels, ())
                    self.assertFalse(image.has_pixels())
                    with self.assertRaises(RuntimeError):
                        image.get_plane(0)

    def test_plane_bounds_and_input_contract(self):
        image = ImageWrapper(0, 0, 1, 1, (), "RGBX", 24, 4)
        self.assertFalse(image.has_pixels())
        with self.assertRaises(IndexError):
            image.get_plane(0)
        image.set_pixels((b"0123",))
        for index in (-1, 1):
            with self.assertRaises(IndexError):
                image.get_plane(index)
        for invalid in (None, b"0123", bytearray(4), memoryview(b"0123"), ("text",), (1,)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    image.set_pixels(invalid)
                with self.assertRaises(TypeError):
                    ImageWrapper(0, 0, 1, 1, invalid, "RGBX", 24, 4)

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
        img = ImageWrapper(X, Y, W, H, (buf,), "RGBX", D, W*4, planes=ImageWrapper.PACKED, thread_safe=True)
        #verify attributes:
        assert repr(img)
        assert img.get_x()==X
        assert img.get_y()==Y
        assert img.get_target_x()==X
        assert img.get_target_y()==Y
        assert img.get_width()==W
        assert img.get_height()==H
        assert img.get_depth()==D
        assert img.get_bytesperpixel()==4
        assert img.get_rowstride()==W*4
        assert img.get_size()==W*4*H
        assert img.has_pixels()
        assert len(img.get_geometry())==5
        assert img.get_pixel_format()=="RGBX"
        assert img.get_planes()==ImageWrapper.PACKED
        #print("image pixels head=%s" % (binascii.hexlify(img.get_plane(0)[:128]), ))
        for x in range(3):
            SW, SH = 6, 6
            sub = img.get_sub_image(x, 0, SW, SH)
            #print("%s.get_sub_image%s=%s" % (img, (x, 0, SW, SH), sub))
            #this is only true for the pure python ImageWrapper:
            #(the X11 image wrapper references the same underlying XShm pixels, with the same rowstride)
            assert sub.get_rowstride()==(SW*4)
            sub_buf = sub.get_plane(0)
            #print("pixels for %ix%i: %i" % (SW, SH, len(sub_buf)))
            #print("pixels=%s" % (binascii.hexlify(sub_buf), ))
            #verify that the pixels are set to 1 / 0:
            for y in range(SH):
                v = (x+y) % 256
                for i in range(4):
                    av = sub_buf[y*(SW*4)+i]
                    if av!=v:
                        raise Exception("""expected value %#x for pixel (0, %i)
                                        of sub-image %s at (%i, 0), but got %#x""" % (v, y, sub, x, av))
        start = monotonic()
        copy = img.get_sub_image(0, 0, W, H)
        end = monotonic()
        if SHOW_PERF:
            print("image wrapper full %ix%i copy speed: %iMB/s" % (W, H, (W*4*H)/(end-start)/1024/1024))
        assert copy.get_plane(0)==img.get_plane(0)
        total = 0
        N = 10
        for i in range(N):
            region = (W//4-N//2+i, H//4-N//2+i, W//2, H//2)
            start = monotonic()
            copy = img.get_sub_image(*region)
            end = monotonic()
            total += end-start
        if SHOW_PERF:
            print("image wrapper sub image %ix%i copy speed: %iMB/s" % (W//2, H//2, N*(W//2*4*H//2)/total/1024/1024))
        #invalid sub-image should fail:
        for x, y, w, h in (
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
        img = ImageWrapper(0, 0, 1, 1, [b"0"*10, b"0"*10, b"0"*10, b"0"*10],
                           "YUV420P", 24, 10, 3, planes=ImageWrapper.PLANAR_4)
        img.set_planes(ImageWrapper.PLANAR_3)
        img.clone_pixel_data()
        assert img.may_restride() is False
        img = ImageWrapper(0, 0, 1, 1, (memoryview(b"0"*4),), "BGRA", 24, 4, 4, planes=ImageWrapper.PACKED)
        img.clone_pixel_data()
        assert img.may_restride() is False
        img = ImageWrapper(0, 0, 10, 10, (b"0"*40*10,), "BGRA", 24, 40, 4, planes=ImageWrapper.PACKED)
        #restride bigger:
        img.restride(80)
        #change more attributes:
        img.set_timestamp(img.get_timestamp()+1)
        img.set_pixel_format("RGBA")
        img.set_palette(())
        img.set_pixels((b"1"*10,))
        assert img.allocate_buffer(0, 1)==0
        assert img.get_palette()==()
        assert img.is_thread_safe()
        assert img.get_gpu_buffer() is None
        img.set_rowstride(20)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
