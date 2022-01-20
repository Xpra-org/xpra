#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import hexstr, memoryview_to_bytes
from xpra.codecs import loader
from xpra.codecs.codec_checks import make_test_image


class Test_CSC_Colorspace(unittest.TestCase):

    def _test_csc(self, mod,
                 width=16, height=16,
                 in_csc="BGRX", out_csc="YUV420P",
                 pixel=b"\0\0\0\0", expected=(
                     b'\x10\x10\x10\x10\x10\x10\x10\x10\x10\x10\x10\x10\x10\x10\x10\x10',
                     b'\x80\x80\x80\x80\x80\x80\x80\x80',
                     b'\x80\x80\x80\x80\x80\x80\x80\x80',
                     )):
        loader.load_codec(mod)
        csc_mod = loader.get_codec(mod)
        if not csc_mod:
            print("%s not found" % mod)
            return
        if in_csc not in csc_mod.get_input_colorspaces():
            raise Exception("%s does not support %s as input" % (mod, in_csc))
        if out_csc not in csc_mod.get_output_colorspaces(in_csc):
            raise Exception("%s does not support %s as output for %s" % (mod, out_csc, in_csc))
        csc = csc_mod.ColorspaceConverter()
        csc.init_context(width, height, in_csc,
                         width, height, out_csc)
        image = make_test_image(in_csc, width, height)
        size = image.get_rowstride()//4*image.get_height()
        bgrx = pixel*size
        image.set_pixels(bgrx)
        out_image = csc.convert_image(image)
        csc.clean()
        assert out_image.get_planes()>=len(expected)
        #now verify the value for each plane specified:
        for i, v in enumerate(expected):
            plane = out_image.get_pixels()[i]
            #plane_stride = out_image.get_rowstride()[i]
            #assert len(plane)>=plane_stride*out_image.get_height()
            plane_bytes = memoryview_to_bytes(plane)
            if plane_bytes[:len(v)]!=v:
                raise Exception("plane %s, expected %s but got %s" % (
                    out_csc[i], hexstr(v), hexstr(plane_bytes[:len(v)])))
            print("%s %s : %s (%i bytes - %s)" % (mod, out_csc[i], hexstr(plane), len(plane), type(plane)))

    def test_BGRX_to_YUV420P(self):
        for mod in loader.CODEC_OPTIONS:
            if not mod.startswith("csc_"):
                continue
            #black:
            self._test_csc(mod)
            #white:
            self._test_csc(mod,
                           pixel=b"\xff\xff\xff\xff", expected=(
                               b'\xeb\xeb\xeb\xeb\xeb\xeb\xeb\xeb\xeb\xeb\xeb\xeb\xeb\xeb\xeb\xeb',
                               b'\x80\x80\x80\x80\x80\x80\x80\x80',
                               b'\x80\x80\x80\x80\x80\x80\x80\x80',
                               )
                           )


def main():
    unittest.main()

if __name__ == '__main__':
    main()
