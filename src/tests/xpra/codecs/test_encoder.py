#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
from tests.xpra.codecs.test_codec import make_planar_input, make_rgb_input
from xpra.codecs.image_wrapper import ImageWrapper

DEFAULT_TEST_DIMENSIONS = ((32, 32), (1920, 1080), (512, 512))


def test_encoder(encoder_module, dimensions=DEFAULT_TEST_DIMENSIONS, options={}):
    print("test_encoder(%s, %s)" % (encoder_module, dimensions))
    print("colorspaces=%s" % encoder_module.get_colorspaces())
    for c in encoder_module.get_colorspaces():
        print("spec(%s)=%s" % (c, encoder_module.get_spec(c)))
    print("version=%s" % str(encoder_module.get_version()))
    print("type=%s" % encoder_module.get_type())
    ec = getattr(encoder_module, "Encoder")
    print("encoder class=%s" % ec)

    seed = 0
    for src_format in encoder_module.get_colorspaces():
        for w,h in dimensions:
            print("* %s @ %sx%s" % (src_format, w, h))
            e = ec()
            print("instance=%s" % e)
            e.init_context(w, h, src_format, 20, 0, options)
            print("initialiazed instance=%s" % e)
            for i in range(10):
                print("testing with image %s" % i)
                #create a dummy ImageWrapper to compress:
                if src_format.startswith("YUV"):
                    strides, pixels = make_planar_input(src_format, w, h, use_strings=False, populate=True, seed=seed)
                else:
                    pixels = make_rgb_input(src_format, w, h, use_strings=False, populate=True)
                    strides = w*3
                image = ImageWrapper(0, 0, w, h, pixels, src_format, 24, strides, planes=ImageWrapper._3_PLANES)
                print("calling %s(%s)" % (e.compress_image, image))
                c = e.compress_image(image)
                assert c is not None, "no image!"
                data, _ = c
                print("data size: %s" % len(data))
                print("data head: %s" % binascii.hexlify(data[:2048]))
                seed += 10
