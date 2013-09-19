#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import threading
from tests.xpra.codecs.test_encoder import test_encoder, gen_src_images, do_test_encoder
#TEST_DIMENSIONS = ((32, 32), (1920, 1080), (512, 512))
TEST_DIMENSIONS = ((1920, 1080), (512, 512), (32, 32))

def test_encode_one():
    from xpra.codecs.nvenc import encoder   #@UnresolvedImport
    print("")
    print("test_nvenc()")
    test_encoder(encoder)
    print("")

def test_encode_all_GPUs():
    from xpra.codecs.nvenc import encoder as encoder_module   #@UnresolvedImport
    cuda_devices = encoder_module.get_cuda_devices()
    print("")
    print("test_parallel_encode() will test one encoder on each of %s sequentially" % cuda_devices)
    TEST_DIMENSIONS = [(32, 32)]
    for device_id, info in cuda_devices.items():
        options = {"cuda_device" : device_id}
        print("")
        print("**********************************")
        print("**********************************")
        print("testing on  %s : %s" % (device_id, info))
        test_encoder(encoder_module, options, TEST_DIMENSIONS)
    print("")

def test_context_limits():
    #figure out how many contexts we can have on each card:
    from xpra.codecs.nvenc import encoder as encoder_module   #@UnresolvedImport
    cuda_devices = encoder_module.get_cuda_devices()
    ec = getattr(encoder_module, "Encoder")
    MAX_ENCODER_CONTEXTS_PER_DEVICE = 64
    print("")
    for w,h in TEST_DIMENSIONS:
        print("test_context_limits() %sx%s" % (w, h))
        src_format = encoder_module.get_colorspaces()[0]
        for device_id, device_info in cuda_devices.items():
            options = {"cuda_device" : device_id}
            encoders = []
            for i in range(MAX_ENCODER_CONTEXTS_PER_DEVICE):
                e = ec()
                encoders.append(e)
                try:
                    e.init_context(w, h, src_format, 20, 0, options)
                except Exception, e:
                    print("failed to created context %s on %s: %s" % (i, device_info, e))
                    break
            print("device %s managed %s contexts at %sx%s" % (device_info, len(encoders)-1, w, h))
            for encoder in encoders:
                try:
                    encoder.clean()
                except Exception, e:
                    print("encoder cleanup error: %s" % e)
    print("")

def test_parallel_encode():
    from xpra.codecs.nvenc import encoder as encoder_module   #@UnresolvedImport
    cuda_devices = encoder_module.get_cuda_devices()
    ec = getattr(encoder_module, "Encoder")
    print("")
    print("test_parallel_encode() will test one %s encoder on each of %s in parallel" % (ec, cuda_devices))
    w, h = 1920, 1080
    IMAGE_COUNT = 20
    ENCODER_CONTEXTS_PER_DEVICE = 4
    src_format = encoder_module.get_colorspaces()[0]
    print("generating %s images..." % IMAGE_COUNT)
    images = []
    for _ in range(IMAGE_COUNT):
        images += gen_src_images(src_format, w, h, 1)
        sys.stdout.write(".")
        sys.stdout.flush()
    print("%s images generated" % IMAGE_COUNT)
    encoders = []
    for device_id, device_info in cuda_devices.items():
        options = {"cuda_device" : device_id}
        for i in range(ENCODER_CONTEXTS_PER_DEVICE):
            e = ec()
            e.init_context(w, h, src_format, 20, 0, options)
            print("encoder %s for device %s initialized" % (i, device_id))
            info = "%s / encoder %s" % (device_info, i)
            encoders.append((info, e, images))
    print("%s encoders initialized: %s" % (len(encoders), [e[1] for e in encoders]))
    threads = []
    i = 0
    for info, encoder, images in encoders:
        name = "Card %s : %s" % (i, info)
        thread = threading.Thread(target=encoding_thread, name=name, args=(encoder, src_format, w, h, images, name))
        threads.append(thread)
        i += 1
    print("%s threads created: %s" % (len(threads), threads))
    print("starting all threads")
    print("")
    for thread in threads:
        thread.start()
    print("%s threads started - waiting for completion" % len(threads))
    for thread in threads:
        thread.join()
    print("all threads ended")
    for _, encoder, _ in encoders:
        encoder.clean()
    print("")


def encoding_thread(encoder, src_format, w, h, images, info):
    #print("encoding_thread(%s, %s, %s, %s, %s, %s)" % (encoder, src_format, w, h, images, info))
    print("%s started" % info)
    do_test_encoder(encoder, src_format, w, h, images, name=info, log_data=False, pause=0.25)

def main():
    import logging
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(logging.StreamHandler(sys.stdout))
    print("main()")
    #test_encode_one()
    #test_encode_all_GPUs()
    test_context_limits()
    #test_parallel_encode()


if __name__ == "__main__":
    main()
