#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
def hl(x):
    return binascii.hexlify(x)
def uhl(x):
    return binascii.unhexlify(x)

def do_test_rountrip(i_data, c_data=None):
    from lz4 import LZ4_compress, LZ4_uncompress        #@UnresolvedImport
    c = LZ4_compress(i_data)
    if c_data is not None:
        assert c_data==c, "expected compressed data to look like %s, but got %s" % (hl(c_data), hl(c))
    d = LZ4_uncompress(c)
    assert d==i_data, "expected decompressed data to look like original %s, but got %s" % (hl(i_data), hl(d))

def test_rountrip():
    do_test_rountrip(uhl("f"*1896), uhl("b40300001fff0100ffffff9e50ffffffffff"))
    do_test_rountrip(uhl("deadbeef"), uhl("0400000040deadbeef"))
    do_test_rountrip(uhl("010203040506070809a0b0c0d0e0f0"*10), uhl("96000000ff00010203040506070809a0b0c0d0e0f00f006f50b0c0d0e0f0"))
    print("OK")


def main():
    test_rountrip()


if __name__ == "__main__":
    main()
