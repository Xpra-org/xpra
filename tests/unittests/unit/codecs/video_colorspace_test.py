#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import binascii

from xpra.util import typedict
from xpra.os_util import hexstr
from xpra.codecs import loader
from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.codecs.codec_checks import make_test_image
from xpra.codecs.video_helper import (
    getVideoHelper,
    ALL_VIDEO_ENCODER_OPTIONS, ALL_CSC_MODULE_OPTIONS, ALL_VIDEO_DECODER_OPTIONS,
    )


def h2b(s):
    return binascii.unhexlify(s)

def cmpp(p1, p2, tolerance=3):
    #compare planes, tolerate a rounding difference
    l = min(len(p1), len(p2))
    for i in range(l):
        v1 = p1[i]
        v2 = p2[i]
        if abs(v2-v1)>tolerance:
            return False
    return True

#samples as generated using the csc_colorspace_test:
#(studio-swing)
SAMPLE_YUV420P_IMAGES = {
    "black" : (
        0x00,   #Y
        0x80,   #U
        0x80,   #V
        ),
    "white" : (
        0xFF,   #Y
        0x80,   #U
        0x80,   #V
        ),
    "blue" : (
        0x29,
        0xEF,
        0x6E,
        ),
    }


class Test_Roundtrip(unittest.TestCase):

    def test_all(self):
        vh = getVideoHelper()
        vh.set_modules(ALL_VIDEO_ENCODER_OPTIONS, ALL_CSC_MODULE_OPTIONS, ALL_VIDEO_DECODER_OPTIONS)
        vh.init()
        #info = vh.get_info()
        encodings = vh.get_encodings()
        decodings = vh.get_decodings()
        common = [x for x in encodings if x in decodings]
        for encoding in common:
            encs = vh.get_encoder_specs(encoding)
            decs = vh.get_decoder_specs(encoding)
            for csc_in, encoders in encs.items():
                decoders = decs.get(csc_in)
                if not decoders:
                    continue
                for encoder in encoders:
                    csc = encoder.input_colorspace
                    for dname, decoder in decoders:
                        if csc not in ("YUV420P", "YUV422P", "YUV444P"):
                            continue
                        self._test(encoding, encoder.codec_class, decoder.Decoder, csc)
            #input_colorspace
            print(f"encs={encs}")
#        raise Exception("fail")

    def test_YUV420P(self):
        for encoding, encoder_name, decoder_name in (
            ("vp8", "enc_vpx", "dec_vpx"),
            ("vp9", "enc_vpx", "dec_vpx"),
            ("vp8", "enc_vpx", "dec_avcodec2"),
            ("vp9", "enc_vpx", "dec_avcodec2"),
            ("h264", "enc_x264", "dec_avcodec2"),
            #("h265", "enc_x265", "dec_avcodec2"),
            ):
            self._test_roundtrip(encoding, encoder_name, decoder_name)

    def test_YUV444P(self):
        for encoding, encoder_name, decoder_name in (
            ("h264", "enc_x264", "dec_avcodec2"),
            ):
            self._test_roundtrip(encoding, encoder_name, decoder_name)

    def _test_roundtrip(self, encoding="vp8", encoder_name="enc_vpx", decoder_name="dec_vpx", csc="YUV420P"):
        encoder_module = loader.load_codec(encoder_name)
        if not encoder_module:
            print(f"{encoder_name} not found")
            return
        try:
            encoder_module.get_input_colorspaces(encoding)
        except Exception:
            print(f"{encoder_name} does not support {encoding}")
            return
        if csc not in encoder_module.get_input_colorspaces(encoding):
            raise Exception(f"{encoder_module} does not support {csc} as input")
        decoder_module = loader.load_codec(decoder_name)
        if not decoder_module:
            print(f"{decoder_name} not found")
            return
        self._test(encoding, encoder_module.Encoder, decoder_module.Decoder, csc)

    def _test(self, encoding, encoder_class, decoder_class, csc="YUV420P"):
        for colour, yuvdata in SAMPLE_YUV420P_IMAGES.items():
            try:
                self._test_data(encoding, encoder_class, decoder_class, csc, yuvdata)
            except Exception:
                print(f"error with {colour} {encoding} image via {encoder_class} and {decoder_class}")
                raise

    def _test_data(self, encoding, encoder_class, decoder_class, csc="YUV420P",
                      yuvdata=None, width=128, height=128):
        #print("test_data%s" % ((encoding, encoder_class, decoder_class, csc, len(yuvdata), width, height),))
        encoder = encoder_class()
        options = typedict({"max-delayed" : 0})
        encoder.init_context(encoding, width, height, csc, options)
        in_image = make_test_image(csc, width, height)
        yuv = []
        rowstrides = []
        divs = get_subsampling_divs(csc)
        for i, bvalue in enumerate(yuvdata):
            xdiv, ydiv = divs[i]
            rowstride = width//xdiv
            rowstrides.append(rowstride)
            size = rowstride*height//ydiv
            yuv.append(chr(bvalue).encode("latin1")*size)
        in_image.set_pixels(yuv)
        in_image.set_rowstride(rowstrides)
        cdata, client_options = encoder.compress_image(in_image)
        assert cdata
        #decode it:
        decoder = decoder_class()
        decoder.init_context(encoding, width, height, csc)
        out_image = decoder.decompress_image(cdata, typedict(client_options))
        #print("%s %s : %s" % (encoding, decoder_module, out_image))
        in_planes = in_image.get_pixels()
        out_planes = out_image.get_pixels()
        for i, plane in enumerate(("Y", "U", "V")):
            in_pdata = in_planes[i]
            out_pdata = out_planes[i]
            xdiv, ydiv = divs[i]
            in_stride = in_image.get_rowstride()[i]
            out_stride = out_image.get_rowstride()[i]
            #compare lines at a time since the rowstride may be different:
            for y in range(height//ydiv):
                in_rowdata = in_pdata[in_stride*y:in_stride*y+width//xdiv]
                out_rowdata = out_pdata[out_stride*y:out_stride*y+width//xdiv]
                if not cmpp(in_rowdata, out_rowdata):
                    raise Exception(f"expected {hexstr(in_rowdata)} but got {hexstr(out_rowdata)}"+
                                    f" for row {y} of plane {plane} with {encoding}")
            #print("%s - %s : %s vs %s" % (encoding, plane, hexstr(in_pdata), hexstr(out_pdata)))


def main():
    unittest.main()

if __name__ == '__main__':
    main()
