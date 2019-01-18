#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import numpy
import random
from xpra.os_util import monotonic_time
from websockify import WebSocketRequestHandler
from xpra.codecs.xor.cyxor import hybi_unmask

def cython_unmask(buf, hlen, plen):
    pstart = hlen + 4
    pend = pstart + plen
    mask = buf[hlen:hlen+4]
    data = buf[pstart:pend]
    return hybi_unmask(mask, data)

def test_unmask(unmask_fn, slice_size, runs=10):
    #make a large random buffer
    buf = numpy.random.randint(256, size=2*slice_size, dtype='B')
    byte_buffer = buf.tobytes()
    total_time = 0
    for _ in range(runs):
        start_offset = random.randint(0, slice_size)
        #slice = byte_buffer[start_offset:start_offset+256*1024*1024]
        start = monotonic_time()
        unmask_fn(byte_buffer, start_offset, slice_size)
        end = monotonic_time()
        total_time += end-start
    return slice_size*runs//total_time

def main():
    for slice_size in (1024, 64*1024, 1024*1024, 16*1024*1024, 64*1024*1024):
        print("* slice size: %iKB" % (slice_size//1024))
        print(" - websockify via numpy:    %iMB/s" % (test_unmask(WebSocketRequestHandler.unmask, slice_size)//1024//1024))
        print(" - xpra cython         :    %iMB/s" % (test_unmask(cython_unmask, slice_size)//1024//1024))


if __name__ == "__main__":
    main()
