#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import binascii
from xpra.codecs.codec_constants import get_subsampling_divs

DEBUG = False


def dump_pixels(pixels):
    S = 64
    t = type(pixels)
    add = []
    if len(pixels)>S:
        v = pixels[:S-1]
        add = ["..."]
    else:
        v = pixels
    if t==buffer:
        l = binascii.hexlify(v) + str(add)
    elif t==bytearray:
        l = binascii.hexlify(str(v)) + str(add)
    elif t==str:
        l = binascii.hexlify(v) + str(add)
    else:
        l = [hex(x) for x in v] + str(add)
    return ("%s %s:%s" % (str(type(pixels)).ljust(20), str(len(pixels)).rjust(8), l)).replace("'","")

def hextobytes(s):
    return bytearray(binascii.unhexlify(s))


def make_rgb_input(src_format, w, h, xratio=1, yratio=1, channelratio=64, use_strings=False, populate=False, seed=0):
    start = time.time()
    bpp = len(src_format)
    assert bpp==3 or bpp==4
    pixels = bytearray("\0" * (w*h*4))
    if populate:
        for y in range(h):
            for x in range(w):
                i = (y*w+x)*bpp
                v = (y*yratio*w+x*xratio)*bpp
                for j in range(3):
                    pixels[i+j] = (v+j*channelratio + seed) % 256
                pixels[i+3] = 0
    end = time.time()
    if DEBUG:
        print("make_rgb_input%s took %.1fms" % ((src_format, w, h, use_strings, populate), end-start))
    if use_strings:
        return str(pixels)
    return pixels

def make_planar_input(src_format, w, h, use_strings=False, populate=False, seed=0):
    assert src_format in ("YUV420P", "YUV422P", "YUV444P"), "invalid source format %s" % src_format
    start = time.time()
    Ydivs, Udivs, Vdivs = get_subsampling_divs(src_format)
    Yxd, Yyd = Ydivs
    Uxd, Uyd = Udivs
    Vxd, Vyd = Vdivs
    Ysize = w*h/Yxd/Yyd
    Usize = w*h/Uxd/Uyd
    Vsize = w*h/Vxd/Vyd
    Ydata = bytearray("\0" * Ysize)
    Udata = bytearray("\0" * Usize)
    Vdata = bytearray("\0" * Vsize)
    if populate:
        for y in range(h):
            for x in range(w):
                i = y*x
                v = seed + i
                Ydata[i/Yxd/Yyd] = v % 256
                Udata[i/Uxd/Uyd] = v % 256
                Vdata[i/Vxd/Vyd] = v % 256
    if use_strings:
        pixels = (str(Ydata), str(Udata), str(Vdata))
    else:
        pixels = (Ydata, Udata, Vdata)
    strides = (w/Yxd, w/Uxd, w/Vxd)
    end = time.time()
    if DEBUG:
        print("make_planar_input%s took %.1fms" % ((src_format, w, h, use_strings, populate), end-start))
    return strides, pixels
