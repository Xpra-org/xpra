#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import binascii
from xpra.codecs.codec_constants import get_subsampling_divs

DEBUG = False

MIN_SIZE = 1024*1024
SOURCE_DATA = None
def get_source_data(size, seed=0):
    global SOURCE_DATA
    if SOURCE_DATA is None or len(SOURCE_DATA)+seed<size:
        print("creating sample data for size %s" % size)
        SOURCE_DATA = bytearray(max(MIN_SIZE, size+seed+1024))
        for i in range(size):
            SOURCE_DATA[i] = i%256
    return SOURCE_DATA[seed:size+seed]


def dump_pixels(pixels):
    S = 64
    t = type(pixels)
    add = []
    if len(pixels)>S:
        v = pixels[:S-1]
        add = ["..."]
    else:
        v = pixels
    if t==bytearray:
        l = binascii.hexlify(str(v)) + str(add)
    elif t==str:
        l = binascii.hexlify(v) + str(add)
    else:
        l = [hex(x) for x in v] + str(add)
    return ("%s %s:%s" % (str(type(pixels)).ljust(20), str(len(pixels)).rjust(8), l)).replace("'","")

def hextobytes(s):
    return bytearray(binascii.unhexlify(s))


def make_rgb_input(src_format, w, h, use_strings=False, populate=False, seed=0):
    start = time.time()
    bpp = len(src_format)
    assert bpp in (3, 4)
    size = w*h*bpp
    if populate:
        pixels = bytearray(get_source_data(size, seed))
    else:
        pixels = bytearray(size)
    end = time.time()
    if DEBUG:
        print("make_rgb_input%s took %.1fms" % ((src_format, w, h, use_strings, populate), end-start))
    if use_strings:
        return str(pixels)
    return pixels

def make_planar_input(src_format, w, h, use_strings=False, populate=False, seed=0):
    assert src_format in ("YUV420P", "YUV422P", "YUV444P", "GBRP"), "invalid source format %s" % src_format
    start = time.time()
    Ydivs, Udivs, Vdivs = get_subsampling_divs(src_format)
    Yxd, Yyd = Ydivs
    Uxd, Uyd = Udivs
    Vxd, Vyd = Vdivs
    Ysize = w*h//Yxd//Yyd
    Usize = w*h//Uxd//Uyd
    Vsize = w*h//Vxd//Vyd
    def make_buffer(size):
        if populate:
            return bytearray(get_source_data(size, seed))
        else:
            return bytearray(size)
    Ydata = make_buffer(Ysize)
    Udata = make_buffer(Usize)
    Vdata = make_buffer(Vsize)
    if use_strings:
        pixels = (str(Ydata), str(Udata), str(Vdata))
    else:
        pixels = (Ydata, Udata, Vdata)
    strides = (w//Yxd, w//Uxd, w//Vxd)
    end = time.time()
    if DEBUG:
        print("make_planar_input%s took %.1fms" % ((src_format, w, h, use_strings, populate), end-start))
    return strides, pixels
