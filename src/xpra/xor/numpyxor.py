# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from numpy import frombuffer, bitwise_xor, byte

def xor_str(aa, bb):
    assert len(aa)==len(bb), "cannot xor strings of different lengths (numpyxor)"
    a = frombuffer(aa, dtype=byte)
    b = frombuffer(bb, dtype=byte)
    c = bitwise_xor(a, b)
    return c.tostring()
