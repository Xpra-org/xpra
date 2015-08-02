#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time

from tests.xpra.codecs.test_codec import get_source_data
from xpra.codecs.xor.cyxor import xor_str     #@UnresolvedImport

N = 10

def _test_functions(*fns):
    #1 frame of 4k 32bpp:
    size = 1024*1024*4
    s1 = get_source_data(size)
    s2 = get_source_data(size)
    for fn in fns:
        start = time.time()
        for _ in range(N):
            fn(s1, s2)
        end = time.time()
        elapsed = end-start
        print("%60s took %5ims: %5i MB/s" % (fn, elapsed*1000//N, size*N/1024/1024/elapsed))

def test_xor_str():
    print("test_xor_str()")
    _test_functions(xor_str)

def main():
    test_xor_str()


if __name__ == "__main__":
    main()
