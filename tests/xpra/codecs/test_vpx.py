#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from tests.xpra.codecs.test_encoder import test_performance
from tests.xpra.codecs.test_video_codec import do_test_codec_roundtrip
from xpra.codecs.vpx import encoder as vpx_encoder     #@UnresolvedImport
from xpra.codecs.vpx.decoder import Decoder     #@UnresolvedImport
from xpra.codecs.vpx.encoder import Encoder     #@UnresolvedImport

def test_roundtrip():
    for encoding in ("vp8", "vp9"):
        print("")
        print("test_roundtrip() %s" % encoding)
        for populate in (True, False):
            src_formats = vpx_encoder.get_input_colorspaces(encoding)       #@UndefinedVariable
            print("test_roundtrip() src_formats(%s)=%s" % (encoding, src_formats))
            for src_format in src_formats:
                do_test_codec_roundtrip(Encoder, Decoder, encoding, src_format, [src_format], 640, 480, populate)

def test_perf():
    test_performance(vpx_encoder)


def main():
    #test_roundtrip()
    test_perf()


if __name__ == "__main__":
    main()
