#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.codecs.xor.cyxor import xor_str
import binascii
def h(v):
    return binascii.hexlify(v)

class TestHMAC(unittest.TestCase):

    def fail_xor(self, in1, in2):
        try:
            xor_str(in1, in2)
        except:
            return
        raise Exception("xor_str did not fail on %s / %s", h(in1), h(in2))
    
    def check_xor(self, in1, in2, expected):
        out = xor_str(in1, in2)
        #print("xor_str(%s, %s)=%s" % (h(in1), h(in2), h(out)))
        assert out==expected
    
    def test_xor_str(self):
        zeroes  = chr(0)*16
        ones    = chr(1)*16
        ff      = chr(255)*16
        fe      = chr(254)*16
        empty   = ""
        lstr    = "\0x80"*64
        self.check_xor(zeroes, zeroes, zeroes)
        self.check_xor(ones, ones, zeroes)
        self.check_xor(ff, ones, fe)
        self.check_xor(fe, ones, ff)
        #feed some invalid data:
        self.fail_xor(ones, empty)
        self.fail_xor(empty, zeroes)
        self.fail_xor(lstr, ff)
        self.fail_xor(bool, int)
    

def main():
    unittest.main()

if __name__ == '__main__':
    main()
