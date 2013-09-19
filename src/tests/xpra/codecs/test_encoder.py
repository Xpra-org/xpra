#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import binascii
from tests.xpra.codecs.test_codec import make_planar_input, make_rgb_input
from xpra.codecs.image_wrapper import ImageWrapper

DEFAULT_TEST_DIMENSIONS = [(32, 32), (1920, 1080), (512, 512)]


def test_encoder(encoder_module, options={}, dimensions=DEFAULT_TEST_DIMENSIONS):
    print("test_encoder(%s, %s)" % (encoder_module, dimensions))
    print("colorspaces=%s" % str(encoder_module.get_colorspaces()))
    for encoding in encoder_module.get_encodings():
        for c in encoder_module.get_colorspaces():
            print("spec(%s)=%s" % (c, encoder_module.get_spec(encoding, c)))
    print("version=%s" % str(encoder_module.get_version()))
    print("type=%s" % encoder_module.get_type())
    ec = getattr(encoder_module, "Encoder")
    print("encoder class=%s" % ec)

    N_IMAGES = 2
    for encoding in encoder_module.get_encodings():
        for src_format in encoder_module.get_colorspaces():
            for w,h in dimensions:
                print("")
                print("* %s @ %sx%s to %s" % (src_format, w, h, encoding))
                e = ec()
                print("instance=%s" % e)
                e.init_context(w, h, src_format, encoding, 20, 0, options)
                print("initialiazed instance=%s" % e)
                images = gen_src_images(src_format, w, h, N_IMAGES)
                print("test images generated - starting compression")
                do_test_encoder(e, src_format, w, h, images)

def gen_src_images(src_format, w, h, nframes):
    seed = 0
    images = []
    for _ in range(nframes):
        #create a dummy ImageWrapper to compress:
        if src_format.startswith("YUV"):
            strides, pixels = make_planar_input(src_format, w, h, use_strings=False, populate=True, seed=seed)
        else:
            pixels = make_rgb_input(src_format, w, h, use_strings=False, populate=True)
            strides = w*3
        image = ImageWrapper(0, 0, w, h, pixels, src_format, 24, strides, planes=ImageWrapper._3_PLANES)
        images.append(image)
        seed += 10
    return images

def do_test_encoder(encoder, src_format, w, h, images, name="encoder", log_data=True, pause=0):
    start = time.time()
    for image in images:
        if log_data:
            print("calling %s(%s)" % (encoder.compress_image, image))
        c = encoder.compress_image(image)
        assert c is not None, "no image!"
        data, _ = c
        if log_data:
            print("data size: %s" % len(data))
            print("data head: %s" % binascii.hexlify(data[:2048]))
        if pause>0:
            time.sleep(pause)
    end = time.time()
    print("%s finished encoding %s frames at %sx%s, total encoding time: %.1fms" % (name, len(images), w, h, 1000.0*(end-start)))
