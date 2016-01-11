#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii

def test_decoder(decoder_module, w, h, dst_format, hex_data_list):
    print("test_decoder(%s, %s, %s, %s, %s frames)" % (decoder_module, w, h, dst_format, len(hex_data_list)))
    print("colorspaces=%s" % decoder_module.get_colorspaces())
    print("version=%s" % str(decoder_module.get_version()))
    print("type=%s" % decoder_module.get_type())
    decoder_module.init_module()
    dc = getattr(decoder_module, "Decoder")
    print("decoder class=%s" % dc)
    d = dc()
    print("instance=%s" % d)
    try:
        d.init_context(32, 32, "YUV420P")
        i = 0
        for hex_data in hex_data_list:
            data = binascii.unhexlify(hex_data)
            img = d.decompress_image(data, {})
            print("decoded image(%s - %s bytes)=%s" % (i, len(hex_data), img))
            i += 1
    finally:
        d.clean()
    decoder_module.cleanup_module()
