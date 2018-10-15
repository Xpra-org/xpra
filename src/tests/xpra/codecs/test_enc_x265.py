#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from tests.xpra.codecs.test_encoder import test_encoder, test_performance

def test_enc_x265():
    print("test_enc_x265()")
    from xpra.codecs.enc_x265 import encoder #@UnresolvedImport
    test_encoder(encoder)
    test_performance(encoder)


def main():
    test_enc_x265()


if __name__ == "__main__":
    main()
