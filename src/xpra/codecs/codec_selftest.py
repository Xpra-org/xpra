# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
from xpra.log import Logger
log = Logger("util")


#this test data was generated using a 24x16 blank image as input
TEST_COMPRESSED_DATA = {
    "vp8" : {"YUV420P" : binascii.unhexlify("1003009d012a1800100000070885858899848800281013ad501fc01fd01050122780feffbb029ffffa2546bd18c06f7ffe8951fffe8951af46301bdfffa22a00")},
    "vp9" : {"YUV420P" : binascii.unhexlify("8249834200017000f60038241c18000000200000047ffffffba9da00059fffffff753b413bffffffeea7680000"),
             "YUV444P" : binascii.unhexlify("a249834200002e001ec007048383000000040000223fffffeea76800c7ffffffeea7680677ffffff753b40081000")},
}
W = 24
H = 16

def testdecoder(decoder_module):
    for encoding in decoder_module.get_encodings():
        test_data_set = TEST_COMPRESSED_DATA.get(encoding)
        if not test_data_set:
            log("%s: no test data for %s", decoder_module.get_type(), encoding)
            continue
        for cs in decoder_module.get_input_colorspaces(encoding):
            test_data = test_data_set.get(cs)
            if not test_data:
                continue
            log("%s: testing %s / %s", decoder_module.get_type(), encoding, cs)
            e = decoder_module.Decoder()
            try:
                e.init_context(encoding, W, H, cs)
                image = e.decompress_image(test_data, {})
                assert image is not None, "failed to decode test data for encoding '%s' with colorspace '%s'" % (encoding, cs)
                assert image.get_width()==W, "expected image of width %s but got %s" % (W, image.get_width())
                assert image.get_height()==H, "expected image of height %s but got %s" % (H, image.get_height())
            finally:
                e.clean()
