#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii

def test_dec_avcodec():
    print("test_dec_avcodec()")
    from xpra.codecs.dec_avcodec import decoder #@UnresolvedImport
    print("decoder module=%s" % decoder)
    print("colorspaces=%s" % decoder.get_colorspaces())
    print("version=%s" % str(decoder.get_version()))
    print("type=%s" % decoder.get_type())
    dc = getattr(decoder, "Decoder")
    print("decoder class=%s" % dc)

    d = dc()
    try:
        d.init_context(1920, 1080, "YUV420P")
        hex_data = "000000016764001eac2b4040083602010000000168ee3cb0"
        data = binascii.unhexlify(hex_data)
        img = d.decompress_image(data, {})
        print("decoded image(%s)=%s" % (hex_data, img))
    finally:
        d.clean()
    

def main():
    import logging
    import sys
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(logging.StreamHandler(sys.stdout))
    test_dec_avcodec()


if __name__ == "__main__":
    main()
