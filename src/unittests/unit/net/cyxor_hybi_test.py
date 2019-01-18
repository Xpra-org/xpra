#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import numpy
import binascii
import unittest

from xpra.os_util import memoryview_to_bytes
from xpra.util import repr_ellipsized

class Test_cyxor_hybi(unittest.TestCase):

    def test_sameresult(self):
        try:
            try:
                #websockify 0.8.0 and earlier:
                from websockify.websocket import WebSocketRequestHandler    #@UnusedImport
            except ImportError:
                from websockify.websockifyserver import WebSockifyRequestHandler as WebSocketRequestHandler
            from xpra.codecs.xor.cyxor import hybi_unmask
        except ImportError as e:
            print("Warning: cyxor_hybi test skipped because: %s" % (e,))
            return

        def cmp_unmask(buf, hlen, plen):
            c = memoryview_to_bytes(hybi_unmask(buf, hlen, plen))
            w = WebSocketRequestHandler.unmask(buf, hlen, plen)
            assert w==c, "expected %s got %s" % (repr_ellipsized(binascii.hexlify(w)), repr_ellipsized(binascii.hexlify(c)))

        cmp_unmask(b"\0"*8, 0, 4)
        cmp_unmask(b"\0"*64, 0, 32)
        cmp_unmask(b"".join(chr(i) for i in range(10)), 1, 5)   #1+5+4=10
        cmp_unmask(b"".join(chr(i) for i in range(14)), 0, 10)
        cmp_unmask(b"".join(chr(i) for i in range(14)), 1, 9)
        cmp_unmask(b"".join(chr(i) for i in range(128)), 0, 128-4)
        
        BUF_SIZE = 1024*1024
        buf = numpy.random.randint(256, size=BUF_SIZE, dtype='B')
        buf = buf.tobytes()
        cmp_unmask(buf, 1, 5)

        for offset in range(8):
            for div in range(8):
                for extra in range(8):
                    size = BUF_SIZE//2//(2**div)+extra
                    cmp_unmask(buf, offset, size)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
