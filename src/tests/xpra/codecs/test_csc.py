#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import binascii
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import get_subsampling_divs


def test_csc_rgb(csc_module):
    print("")
    perf_measure_rgb(csc_module)
    perf_measure_rgb(csc_module, 512, 512)
    test_csc_rgb1(csc_module)
    test_csc_rgb2(csc_module)


def perf_measure_rgb(csc_module, w=1920, h=1080):
    pixels = bytearray("\0" * (w*h*4))
    for y in range(h):
        for x in range(w):
            i = (y*w+x)*4
            pixels[i] = i % 256
            pixels[i+1] = i % 256
            pixels[i+2] = i % 256
            pixels[i+3] = 0
    start = time.time()
    count = 1024
    pixels = do_test_csc_rgb(csc_module, w, h, pixels, count=count)
    end = time.time()
    print("%s did %sx%s csc %s times in %.1fms" % (csc_module, w, h, count, end-start))
    mpps = float(w*h*count)/(end-start)
    print("**********************")
    print(" testing with %sx%s" % (w, h))
    print("%s MPixels/s" % int(mpps/1024/1024))
    print("**********************")


def test_csc_rgb2(csc_module):
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
    pixels = do_test_csc_rgb(csc_module, w, h, pixels, (("Y", 0, Ystart), ("U", 1, X80), ("V", 2, X80)))

def test_csc_rgb1(csc_module):
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
    pixels = do_test_csc_rgb(csc_module, w, h, pixels, (("Y", 0, Ystart), ("U", 1, Ustart), ("V", 2, Vstart)))


def check_plane(plane, data, expected):
    #chop data to same size as expected sample:
    if type(data) in (buffer, str):
        data = bytearray(data)
    if type(expected) in (buffer, str):
        expected = bytearray(expected)
    actual_data = data[:len(expected)]
    if actual_data==expected:
        return
    print("check_plane(%s, .., ..) expected=%s" % (plane, dump_pixels(expected)))
    print("check_plane(%s, .., ..)   actual=%s" % (plane, dump_pixels(actual_data)))
    assert type(actual_data)==type(expected), "expected result as %s but got %s" % (type(expected), type(actual_data))
    assert len(actual_data)==len(expected), "expected at least %s items but got %s" % (len(expected), len(actual_data))
    #now compare values, with some tolerance for rounding (off by one):
    warned = False
    for i in range(len(expected)):
        va = actual_data[i]
        ve = expected[i]
        if abs(va-ve)>3:
            if not warned:
                print("ERROR! output differs for plane %s" % plane)
                warned = True
            print("* at index %s: expected %s but got %s" % (i, hex(ve), hex(va)))

def dump_pixels(pixels):
    S = 24
    t = type(pixels)
    add = []
    if len(pixels)>S:
        v = pixels[:S-1]
        add = ["..."]
    else:
        v = pixels
    if t==bytearray:
        t=str
        v = str(v)
    if t==str:
        l = binascii.hexlify(v) + str(add)
    else:
        l = [hex(x) for x in v] + add
    return ("%s %s:%s" % (t, len(pixels), l)).replace("'","")


def do_test_csc_rgb(csc_module, w, h, pixels, checks=(), count=1):
    ColorspaceConverterClass = getattr(csc_module, "ColorspaceConverter")
    cc = ColorspaceConverterClass()
    #print("%s()=%s" % (ColorspaceConverterClass, cc))
    cc.init_context(w, h, "BGRX", w, h, "YUV420P")
    print("ColorspaceConverter=%s" % cc)
    print("test_csc() input pixels=%s" % dump_pixels(pixels))
    image = ImageWrapper(0, 0, w, h, pixels, "BGRX", 32, w*4, planes=ImageWrapper.PACKED_RGB)
    for _ in range(count):
        out = cc.convert_image(image)
    print("test_csc() output=%s" % out)
    assert out.get_planes()==ImageWrapper._3_PLANES
    pixels = out.get_pixels()
    assert len(pixels)==3, "expected 3 planes but found: %s" % len(pixels)
    for i in range(3):
        plane = pixels[i]
        print("test_csc() plane[%s]=%s" % (i, type(plane)))
        print("test_csc() len(plane[%s])=%s" % (i, len(plane)))
        print("test_csc() plane data[%s]=%s" % (i, dump_pixels(plane)))
    for plane, index, expected in checks:
        check_plane(plane, pixels[index], expected)
    return pixels


def test_csc_planar(csc_module):
    print("")
    test_csc_planar1(csc_module)
    #perf_measure_planar(ColorspaceConverter, 4096, 2048)
    perf_measure_planar(csc_module, 1920, 1080)
    perf_measure_planar(csc_module, 512, 512)



def make_planar_input(src_format, w, h):
    assert src_format in ("YUV420P", "YUV422P", "YUV444P"), "invalid source format %s" % src_format
    Ydivs, Udivs, Vdivs = get_subsampling_divs(src_format)
    Yxd, Yyd = Ydivs
    Uxd, Uyd = Udivs
    Vxd, Vyd = Vdivs
    Ydata = bytearray("\0" * (w*h/Yxd/Yyd))
    Udata = bytearray("\0" * (w*h/Uxd/Uyd))
    Vdata = bytearray("\0" * (w*h/Vxd/Vyd))
    for y in range(h):
        for x in range(w):
            i = y*x
            Ydata[i/Yxd/Yyd] = i % 256
            Udata[i/Uxd/Uyd] = i % 256
            Vdata[i/Vxd/Vyd] = i % 256
    pixels = (Ydata, Udata, Vdata)
    strides = (w/Yxd, w/Uxd, w/Vxd)
    return strides, pixels

def test_csc_planar1(csc_module, w=256, h=128):
    #get_subsampling_divs()
    e420 = bytearray([0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x88, 0x0, 0xff, 0x0, 0x81, 0x0, 0xff, 0x0, 0x82])
    e422 = bytearray([0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x86, 0x0, 0xff, 0x0, 0x84, 0x0, 0xff, 0x0, 0x84])
    e444 = bytearray([0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x87])
    FMT_TO_EXPECTED_OUTPUT = {"YUV420P"  : e420,
                              "YUV422P"  : e422,
                              "YUV444P"  : e444}
    for src_format in sorted(FMT_TO_EXPECTED_OUTPUT.keys()):
        expected = FMT_TO_EXPECTED_OUTPUT.get(src_format)
        if src_format not in csc_module.get_input_colorspaces():
            print("test_csc_planar1(%s, %s, %s) skipping %s", csc_module, w, h, src_format)
            continue
        strides, pixels = make_planar_input(src_format, w, h)
        pixels = do_test_csc_planar(csc_module, src_format, w, h, strides, pixels)
        print("test_csc_planar1() head of output pixels=%s" % dump_pixels(pixels[:128]))
        check_plane("XRGB", pixels, expected)

def perf_measure_planar(csc_module, w=1920, h=1080):
    for src_format in csc_module.get_input_colorspaces():
        if src_format not in ("YUV420P", "YUV422P", "YUV444P"):
            continue
        strides, pixels = make_planar_input(src_format, w, h)
        start = time.time()
        count = 128
        print("**********************")
        print("testing with %s at %sx%s ..." % (src_format, w, h))
        pixels = do_test_csc_planar(csc_module, src_format, w, h, strides, pixels, count=count)
        end = time.time()
        print("%s did %sx%s csc %s times in %.1fms" % (csc_module, w, h, count, end-start))
        mpps = float(w*h*count)/(end-start)
        print("%s MPixels/s" % int(mpps/1024/1024))
        print("**********************")


def do_test_csc_planar(csc_module, src_format, w, h, strides, pixels, checks=(), count=1):
    assert len(pixels)==3, "this test only handles 3-plane pixels"
    ColorspaceConverterClass = getattr(csc_module, "ColorspaceConverter")
    cc = ColorspaceConverterClass()
    #print("%s()=%s" % (ColorspaceConverterClass, cc))
    cc.init_context(w, h, src_format, w, h, "XRGB")
    print("ColorspaceConverter=%s" % cc)
    #for i in range(3):
    #    print("test_csc() plane[%s]=%s" % (i, dump_pixels(pixels[i])))
    image = ImageWrapper(0, 0, w, h, pixels, src_format, 24, strides, planes=ImageWrapper._3_PLANES)
    for _ in range(count):
        out = cc.convert_image(image)
    print("test_csc() output=%s" % out)
    assert out is not None, "convert_image returned None!"
    assert out.get_planes()==ImageWrapper.PACKED_RGB, "output image is not in packed RGB!"
    #clone the pixels before the wrapper falls out of scope!
    out.clone_pixel_data()
    return out.get_pixels()
