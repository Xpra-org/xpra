#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.codecs.image_wrapper import ImageWrapper



def test_csc(ColorspaceConverter):
    test_csc1(ColorspaceConverter)
    test_csc2(ColorspaceConverter)


def test_csc2(ColorspaceConverter):
    w, h = 32, 32
    pixels = bytearray("\0" * (w*h*4))
    for y in range(h):
        for x in range(w):
            i = (y*w+x)*4
            pixels[i] = i % 256
            pixels[i+1] = i % 256
            pixels[i+2] = i % 256
            pixels[i+3] = 0
    Ystart = bytearray([0x10, 0x13, 0x17, 0x1a])
    X80 = chr(0x80)*256
    pixels = test_csc_pixels(ColorspaceConverter, w, h, pixels, (("Y", 0, Ystart), ("U", 1, X80), ("V", 2, X80)))

def test_csc1(ColorspaceConverter):
    w, h = 16, 16
    pixels = bytearray("\0" * (w*h*4))
    for y in range(h):
        for x in range(w):
            i = (y*w+x)*4
            pixels[i] = i % 256
            pixels[i+1] = (i+128) % 256
            pixels[i+2] = (i+192) % 256
            pixels[i+3] = 0
    Ystart = bytearray([0x82, 0x85, 0x89, 0x8c])
    Ustart = bytearray([0x51, 0x51, 0x51, 0x51, 0x51, 0x51, 0x51, 0x51, 0xaf])
    Vstart = bytearray([0x6d, 0x6d, 0x6d, 0x6d, 0x6d, 0x6d, 0x6d, 0x6d, 0x93])
    pixels = test_csc_pixels(ColorspaceConverter, w, h, pixels, (("Y", 0, Ystart), ("U", 1, Ustart), ("V", 2, Vstart)))

    

def test_csc_pixels(ColorspaceConverter, w, h, pixels, checks=()):
    print("going to create %s" % ColorspaceConverter)
    cc = ColorspaceConverter()
    print("%s()=%s" % (ColorspaceConverter, cc))
    cc.init_context(w, h, "BGRX", w, h, "YUV420P")
    print("ColorspaceConverter=%s" % cc)
    print("test_csc() input pixels=%s" % str([hex(x) for x in pixels]))
    image = ImageWrapper(0, 0, w, h, pixels, "BGRX", 32, w*4, planes=ImageWrapper.PACKED_RGB)
    out = cc.convert_image(image)
    print("test_csc() output=%s" % out)
    assert out.get_planes()==ImageWrapper._3_PLANES
    pixels = out.get_pixels()
    assert len(pixels)==3, "expected 3 planes but found: %s" % len(pixels)
    for i in range(3):
        plane = pixels[i]
        print("test_csc() plane[%s]=%s" % (i, type(plane)))
        print("test_csc() len(plane[%s])=%s" % (i, len(plane)))
        print("test_csc() plane data[%s]=%s" % (i, str([hex(x) for x in bytearray(plane)])))
    def check_plane(plane, data, expected):
        #chop data to same size as expected sample:
        if type(data)==buffer:
            data = bytearray(data)
        if type(expected)==str:
            expected = bytearray(expected)
        actual_data = data[:len(expected)]
        if actual_data==expected:
            return
        print("check_plane(%s, .., ..) expected=%s" % (plane, str([hex(x) for x in expected])))
        print("check_plane(%s, .., ..) actual_data=%s" % (plane, str([hex(x) for x in actual_data])))
        assert type(actual_data)==type(expected), "expected result as %s but got %s" % (type(expected), type(actual_data))
        assert len(actual_data)==len(expected), "expected at least %s items but got %s" % (len(expected), len(actual_data))
        #now compare values, with some tolerance for rounding (off by one):
        for i in range(len(expected)):
            va = actual_data[i]
            ve = expected[i]
            assert abs(va-ve)<=1, "output differs for plane %s at index %s: expected %s but got %s" % (plane, i, ve, va)
    for plane, index, expected in checks:
        check_plane(plane, pixels[index], expected)
    return pixels
