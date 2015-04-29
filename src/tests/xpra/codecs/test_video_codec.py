#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time

from xpra.codecs.image_wrapper import ImageWrapper
#from tests.xpra.test_util import dump_resource_usage, dump_threads
from tests.xpra.codecs.test_codec import make_rgb_input, make_planar_input


def do_test_codec_roundtrip(encoder_class, decoder_class, encoding, src_format, dst_formats, w, h, populate):
    quality = 100
    speed = 100
    scaling = (1,1)
    options = {}

    start = time.time()
    encoder = encoder_class()
    #print("%s%s" % (encoder.init_context, (w, h, src_format, dst_formats, encoding, quality, speed, scaling, options)))
    encoder.init_context(w, h, src_format, dst_formats, encoding, quality, speed, scaling, options)
    end = time.time()
    print("encoder %s initialized in %.1fms" % (encoder, 1000.0*(end-start)))

    start = time.time()
    decoder = decoder_class()
    decoder.init_context(encoding, w, h, src_format)
    end = time.time()
    print("decoder %s initialized in %.1fms" % (decoder, 1000.0*(end-start)))

    for i in range(4):

        if src_format.find("RGB")>=0 or src_format.find("BGR")>=0:
            pixels = make_rgb_input(src_format, w, h, populate=populate, seed=i)
            isize = len(pixels)
            stride = len(src_format)*w
            #print(" input pixels: %s (%sx%s, stride=%s, stride*h=%s)" % (len(pixels), w, h, stride, stride*h))
            assert len(pixels)>=stride*h, "not enough pixels! (expected at least %s but got %s)" % (stride*h, len(pixels))
            image = ImageWrapper(0, 0, w, h, pixels, src_format, 24, stride, planes=ImageWrapper.PACKED)
        else:
            strides, pixels = make_planar_input(src_format, w, h, populate=populate)
            isize = sum([len(x) for x in pixels])
            image = ImageWrapper(0, 0, w, h, pixels, src_format, 24, strides, planes=ImageWrapper._3_PLANES)

        print("FRAME %s" % i)
        print("using %s to compress %s" % (encoder, image))
        start = time.time()
        data, options = encoder.compress_image(image)
        end = time.time()
        assert data is not None, "compression failed"
        print("compressed %s bytes down to %s (%.1f%%) in %.1fms" % (isize, len(data), 100.0*len(data)/isize, 1000.0*(end-start)))

        print("uncompressing %s bytes using %s" % (len(data), decoder))
        options['csc'] = src_format
        start = time.time()
        out_image = decoder.decompress_image(data, options)
        end = time.time()
        assert out_image is not None, "decompression failed"
        print("uncompressed to %s in %.1fms" % (str(out_image), 1000.0*(end-start)))
