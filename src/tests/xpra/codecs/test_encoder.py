#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import binascii
from tests.xpra.codecs.test_codec import make_planar_input, make_rgb_input
from xpra.codecs.image_wrapper import ImageWrapper

from xpra.log import Logger
log = Logger("encoder", "test")

DEFAULT_TEST_DIMENSIONS = [(32, 32), (72, 72), (256, 256), (1920, 1080), (512, 512)]


def test_encoder_dimensions(encoder_module):
    log("")
    log("test_encoder_dimensions()")
    dims = []
    for w in (1, 2, 32, 499, 769, 999, 4096, 8192):
        for h in (1, 2, 32, 100, 499, 769, 999, 4096, 8192):
            dims.append((w, h))
    test_encoder(encoder_module, dimensions=dims)
    log("")

def test_performance(encoder_module, options={}):
    log("")
    log("test_encoder_dimensions()")
    dims = [(1920, 1080), (1280, 720)]
    for speed in (0, 100):
        for quality in (0, 80, 100):
            log.info("testing speed=%s, quality=%s", speed, quality)
            test_encoder(encoder_module, options, dims, 100, quality, speed)
    log("")


def log_output(args):
    log(args)

def test_encoder(encoder_module, options={}, dimensions=DEFAULT_TEST_DIMENSIONS, n_images=2, quality=20, speed=0, after_encode_cb=None):
    encoder_module.init_module()
    log("test_encoder(%s, %s)", encoder_module, dimensions)
    log("version=%s" % str(encoder_module.get_version()))
    log("type=%s" % encoder_module.get_type())
    ec = getattr(encoder_module, "Encoder")
    log("encoder class=%s" % ec)

    for encoding in encoder_module.get_encodings():
        ics = encoder_module.get_input_colorspaces(encoding)
        log("input colorspaces(%s)=%s", encoding, ics)
        for ic in ics:
            for e in encoder_module.get_encodings():
                ocs = encoder_module.get_output_colorspaces(e, ic)
                for c in ocs:
                    log("spec(%s)=%s" % (c, encoder_module.get_spec(e, ic)))
        for src_format in ics:
            spec = encoder_module.get_spec(encoding, src_format)
            for w,h in dimensions:
                for dst_format in ocs:
                    log("%sx%s max: %sx%s" % (w, h, spec.max_w, spec.max_h))
                    if w<spec.min_w:
                        log("not testing %sx%s (min width is %s)" % (w, h, spec.min_w))
                        continue
                    if h<spec.min_h:
                        log("not testing %sx%s (min height is %s)" % (w, h, spec.min_h))
                        continue
                    if w>spec.max_w:
                        log("not testing %sx%s (max width is %s)" % (w, h, spec.max_w))
                        continue
                    if h>spec.max_h:
                        log("not testing %sx%s (max height is %s)" % (w, h, spec.max_h))
                        continue
                    actual_w = w & spec.width_mask
                    actual_h = h & spec.height_mask
                    log("* %s @ %sx%s to %s" % (src_format, w, h, encoding))
                    if actual_w!=w or actual_h!=h:
                        log(" actual dimensions used: %sx%s" % (actual_w, actual_h))
                    e = ec()
                    log("instance=%s" % e)
                    e.init_context(actual_w, actual_h, src_format, [dst_format], encoding, quality, speed, (1, 1), options)
                    #init_context(self, int width, int height, src_format, dst_formats, encoding, int quality, int speed, scaling, options={}):
                    log("initialiazed instance=%s" % e)
                    images = gen_src_images(src_format, actual_w, actual_h, n_images)
                    log("test images generated - starting compression")
                    do_test_encoder(e, src_format, actual_w, actual_h, images, log=log, after_encode_cb=after_encode_cb)
                    e.clean()

def gen_src_images(src_format, w, h, nframes):
    seed = 0
    images = []
    for _ in range(nframes):
        #create a dummy ImageWrapper to compress:
        if src_format.startswith("YUV"):
            strides, pixels = make_planar_input(src_format, w, h, use_strings=False, populate=True, seed=seed)
            planes = ImageWrapper._3_PLANES
        else:
            pixels = make_rgb_input(src_format, w, h, use_strings=False, populate=True)
            strides = w*3
            planes = ImageWrapper.PACKED
        image = ImageWrapper(0, 0, w, h, pixels, src_format, 24, strides, planes=planes)
        images.append(image)
        seed += 10
    return images

def do_test_encoder(encoder, src_format, w, h, images, name="encoder", log=None, pause=0, after_encode_cb=None):
    start = time.time()
    tsize = 0
    for image in images:
        log("calling %s(%s)" % (encoder.compress_image, image))
        c = encoder.compress_image(image)
        assert c is not None, "no image!"
        data, _ = c
        tsize += len(data)
        log("data size: %s" % len(data))
        log("data head: %s" % binascii.hexlify(data[:2048]))
        if pause>0:
            time.sleep(pause)
        if after_encode_cb:
            after_encode_cb(encoder)
    end = time.time()
    #log.info("%s finished encoding %s frames at %sx%s, total encoding time: %.1fms" % (name, len(images), w, h, 1000.0*(end-start)))
    perf = int(len(images)*w*h/(end-start)/1024/1024)
    tpf = int(1000*(end-start)/len(images))
    sized = "%sx%s" % (w, h)
    fsize = tsize/len(images)
    log.info("%s finished encoding %s frames at %s: %s MPixels/s, %sms/frame, %sKB/frame (%s)",
             encoder, str(len(images)).rjust(3), sized.rjust(10), str(perf).rjust(4), str(tpf).rjust(4), str(fsize/1024).rjust(8), encoder.get_info().get("pixel_format"))
    #log.info("info=%s", encoder.get_info())
