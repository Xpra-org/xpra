#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import binascii

from xpra.os_util import hexstr, memoryview_to_bytes
from xpra.codecs import loader
from xpra.codecs.codec_checks import make_test_image


def h2b(s):
    return binascii.unhexlify(s)

def cmpp(p1, p2):
    #compare planes, tolerate a rounding difference of 1
    l = min(len(p1), len(p2))
    for i in range(l):
        v1 = p1[i]
        v2 = p2[i]
        if abs(v2-v1)>1:
            return False
    return True


class Test_CSC_Colorspace(unittest.TestCase):

    def _test_csc(self, mod,
                 width=16, height=16,
                 in_csc="BGRX", out_csc="YUV420P",
                 pixel="00000000", expected=()):
        csc_mod = loader.load_codec(mod)
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
        bgrx = h2b(pixel)*size
        image.set_pixels(bgrx)
        out_image = csc.convert_image(image)
        csc.clean()
        assert out_image.get_planes()>=len(expected)
        #now verify the value for each plane specified:
        for i, v_str in enumerate(expected):
            plane = out_image.get_pixels()[i]
            #plane_stride = out_image.get_rowstride()[i]
            #assert len(plane)>=plane_stride*out_image.get_height()
            plane_bytes = memoryview_to_bytes(plane)
            v = h2b(v_str)
            if not cmpp(plane_bytes, v):
                raise Exception("%s: plane %s, expected %s but got %s" % (
                    mod, out_csc[i], v_str, hexstr(plane_bytes[:len(v)])))
            #print("%s %s : %s (%i bytes - %s)" % (mod, out_csc[i], hexstr(plane), len(plane), type(plane)))
            #print("%s : %s" % (out_csc[i], hexstr(plane_bytes)))

    def test_BGRX_to_YUV420P(self):
        width = height = 16
        for mod in loader.CSC_CODECS:
            #black:
            self._test_csc(mod, width, height,
                           pixel="00000000", expected=(
                               "00"*width,
                               "80"*(width//2),
                               "80"*(width//2),
                           ))
            #white:
            self._test_csc(mod, width, height,
                           pixel="ffffffff", expected=(
                               "ff"*width,
                               "80"*(width//2),
                               "80"*(width//2),
                               )
                           )
            #blue?
            self._test_csc(mod, width, height,
                           pixel="ff000000", expected=(
                               "1d"*width,
                               "ff"*(width//2),
                               "6b"*(width//2),
                               )
                           )


def main():
    unittest.main()

if __name__ == '__main__':
    main()
