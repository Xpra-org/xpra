#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from tests.xpra.codecs.test_encoder import test_encoder
TEST_DIMENSIONS = ((32, 32), (1920, 1080), (512, 512))

def test_encode():
    from xpra.codecs.nvenc import encoder   #@UnresolvedImport
    print("test_nvenc()")
    test_encoder(encoder)

def test_parallel_encode():
    from xpra.codecs.nvenc import encoder   #@UnresolvedImport
    cuda_devices = encoder.get_cuda_devices()
    print("test_parallel_encode() will test one encoder on each of %s sequentially" % cuda_devices)
    TEST_DIMENSIONS = [(32, 32)]
    for device_id, info in cuda_devices.items():
        options = {"cuda_device" : device_id}
        print("")
        print("**********************************")
        print("**********************************")
        print("testing on  %s : %s" % (device_id, info))
        test_encoder(encoder, options, TEST_DIMENSIONS)


def main():
    import logging
    import sys
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(logging.StreamHandler(sys.stdout))
    print("main()")
    test_parallel_encode()
    #test_encode()


if __name__ == "__main__":
    main()
