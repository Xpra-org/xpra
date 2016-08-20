#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import numpy as np

from xpra.server.window.motion import CRC_Image


def test_CRC_Image():
    start = time.time()
    N = 100
    W = 1920
    H = 1080
    BPP = 4
    LEN = W * H * BPP
    buf = np.random.randint(256, size=LEN).tobytes()
    ov = CRC_Image(buf, W//4, H, W, 4)
    #print("CRC_Image(..)=%s" % (ov, ))
    for _ in range(N):
        v = CRC_Image(buf, W//4, H, W, 4)
        assert v==ov
        assert len(v)==H
    end = time.time()
    elapsed = end-start
    print("crc32c: %i times %ix%i (%.1fMB) in %.3fs, %.1fGB/s" % (N, W, H, LEN//(1024.0*1024.0), elapsed, ((N*LEN) / (end-start) / (1024*1024*1024))))
    #just for comparing:
    #crc the whole buffer (which is more advantageous)
    from zlib import crc32
    start = time.time()
    v = crc32(buf)
    end = time.time()
    print("zlib.crc32: %.2fMB/s" % ((N*LEN)//(end-start)/(1024*1024*1024)))

def main():
    test_CRC_Image()

if __name__ == "__main__":
    main()
