# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import get_subsampling_divs
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


def make_test_image(pixel_format, w, h):
    if pixel_format.startswith("YUV") or pixel_format=="GBRP":
        divs = get_subsampling_divs(pixel_format)
        ydiv = divs[0]  #always (1,1)
        y = bytearray(b"\0" * (w*h//(ydiv[0]*ydiv[1])))
        udiv = divs[1]
        u = bytearray(b"\0" * (w*h//(udiv[0]*udiv[1])))
        vdiv = divs[2]
        v = bytearray(b"\0" * (w*h//(vdiv[0]*vdiv[1])))
        image = ImageWrapper(0, 0, w, h, [y, u, v], pixel_format, 32, [w//ydiv[0], w//udiv[0], w//vdiv[0]], planes=ImageWrapper._3_PLANES, thread_safe=True)
    elif pixel_format in ("RGB", "BGR", "RGBX", "BGRX", "XRGB", "BGRA", "RGBA"):
        rgb_data = bytearray(b"\0" * (w*h*len(pixel_format)))
        image = ImageWrapper(0, 0, w, h, rgb_data, pixel_format, 32, w*len(pixel_format), planes=ImageWrapper.PACKED, thread_safe=True)
    else:
        raise Exception("don't know how to create a %s image" % pixel_format)
    return image


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
                #test failures:
                try:
                    image = e.decompress_image("junk", {})
                except:
                    pass
                if image is not None:
                    raise Exception("decoding junk with %s should have failed, got %s instead" % (decoder_module.get_type(), image))
            finally:
                e.clean()


def testencoder(encoder_module):
    for encoding in encoder_module.get_encodings():
        for cs_in in encoder_module.get_input_colorspaces(encoding):
            for cs_out in encoder_module.get_output_colorspaces(encoding, cs_in):
                e = encoder_module.Encoder()
                try:
                    e.init_context(W, H, cs_in, [cs_out], encoding, W, H, (1,1), {})
                    image = make_test_image(cs_in, W, H)
                    data, meta = e.compress_image(image)
                    assert len(data)>0
                    assert meta is not None
                    #print("test_encoder: %s.compress_image(%s)=%s" % (encoder_module.get_type(), image, (data, meta)))
                    #import binascii
                    #print("compressed data with %s: %s bytes (%s), metadata: %s" % (encoder_module.get_type(), len(data), type(data), meta))
                    #print("compressed data(%s, %s)=%s" % (encoding, cs_in, binascii.hexlify(data)))
                finally:
                    e.clean()


def testcsc(csc_module):
    for cs_in in csc_module.get_input_colorspaces():
        for cs_out in csc_module.get_output_colorspaces(cs_in):
            log("%s: testing %s / %s", csc_module.get_type(), cs_in, cs_out)
            e = csc_module.ColorspaceConverter()
            try:
                #TODO: test scaling
                e.init_context(W, H, cs_in, W, H, cs_out)
                image = make_test_image(cs_in, W, H)
                out = e.convert_image(image)
                #print("convert_image(%s)=%s" % (image, out))
                assert out.get_width()==W, "expected image of width %s but got %s" % (W, image.get_width())
                assert out.get_height()==H, "expected image of height %s but got %s" % (H, image.get_height())
                assert out.get_pixel_format()==cs_out
                for w,h in ((W*2, H//2), (W//2, H**2)):
                    try:
                        image = make_test_image(cs_in, w, h)
                        out = e.convert_image(image)
                    except:
                        out = None
                    if out is not None:
                        raise Exception("converting an image of a smaller size with %s should have failed, got %s instead" % (csc_module.get_type(), out))
            finally:
                e.clean()
