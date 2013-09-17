#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii

TEST_DIMENSIONS = ((1920, 1080), (512, 512))

def test_nvenc():
    print("test_nvenc()")
    from xpra.codecs.nvenc import encoder #@UnresolvedImport
    print("encoder module=%s" % encoder)
    print("colorspaces=%s" % encoder.get_colorspaces())
    for c in encoder.get_colorspaces():
        print("spec(%s)=%s" % (c, encoder.get_spec(c)))
    print("version=%s" % str(encoder.get_version()))
    print("type=%s" % encoder.get_type())
    ec = getattr(encoder, "Encoder")
    print("encoder class=%s" % ec)

    from tests.xpra.codecs.test_codec import make_planar_input
    from xpra.codecs.image_wrapper import ImageWrapper

    seed = 0
    for src_format in encoder.get_colorspaces():
        for w,h in TEST_DIMENSIONS:
            print("* %s @ %sx%s" % (src_format, w, h))
            e = ec()
            print("instance=%s" % e)
            e.init_context(w, h, src_format, 100, 100, {})
            print("initialiazed instance=%s" % e)
            for i in range(10):
                print("testing with image %s" % i)
                #create a dummy ImageWrapper to compress:
                strides, pixels = make_planar_input(src_format, w, h, use_strings=False, populate=True, seed=seed)
                image = ImageWrapper(0, 0, w, h, pixels, src_format, 24, strides, planes=ImageWrapper._3_PLANES)
                print("calling %s(%s)" % (e.compress_image, image))
                c = e.compress_image(image)
                assert c is not None, "no image!"
                data, _ = c
                print("data size: %s" % len(data))
                print("data head: %s" % binascii.hexlify(data[:128]))
                seed += 10


def main():
    import logging
    import sys
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(logging.StreamHandler(sys.stdout))
    test_nvenc()


if __name__ == "__main__":
    main()
