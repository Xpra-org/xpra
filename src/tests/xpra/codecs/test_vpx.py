#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from tests.xpra.codecs.test_video_codec import do_test_codec_roundtrip
from xpra.codecs.vpx.decoder import Decoder     #@UnresolvedImport
from xpra.codecs.vpx.encoder import Encoder     #@UnresolvedImport

def test_roundtrip():
    for encoding in ("vp8", "vp9"):
        print("")
        print("test_roundtrip() %s" % encoding)
        for populate in (True, False):
            do_test_codec_roundtrip(Encoder, Decoder, encoding, "YUV420P", 640, 480, populate)


def main():
    import logging
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(logging.StreamHandler(sys.stdout))
    print("main()")
    test_roundtrip()


if __name__ == "__main__":
    main()
