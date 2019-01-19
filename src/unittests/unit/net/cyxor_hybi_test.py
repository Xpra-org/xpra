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
                numpy_unmask = WebSocketRequestHandler.unmask
            except ImportError:
                from websockify.websockifyserver import WebSockifyRequestHandler as WebSocketRequestHandler
                numpy_unmask = WebSocketRequestHandler._unmask
            from xpra.codecs.xor.cyxor import hybi_unmask
        except ImportError as e:
            print("Warning: cyxor_hybi test skipped because: %s" % (e,))
            return

        def cmp_unmask(buf, hlen, plen):
            c = memoryview_to_bytes(hybi_unmask(buf, hlen, plen))
            w = numpy_unmask(buf, hlen, plen)
            assert w==c, "expected %s got %s" % (repr_ellipsized(binascii.hexlify(w)), repr_ellipsized(binascii.hexlify(c)))

        #tiny 1 byte buffer
        for hlen in range(8):
            cmp_unmask(b"".join(chr(i) for i in range(hlen+4+1)), hlen, 1)
        #no header and small buffers:
        cmp_unmask(b"\0"*8, 0, 4)
        cmp_unmask(b"\0"*64, 0, 32)

        def fail(buf, hlen, plen):
            for backend, unmask_fn in (
                ("cython", hybi_unmask),
                ("numpy", numpy_unmask),
                ):
                try:
                    unmask_fn(buf, hlen, plen)
                except:
                    pass
                else:
                    raise Exception("%s umask should have failed for buffer of size %i with header=%i and packet len=%i" %
                                    (backend, len(buf), hlen, plen))
        for s in (1, 1024, 1024*1024):
            for header in range(1, 10):
                #buffer too small:
                fail(b"".join(chr(i%256) for i in range(s+4+header-1)), header, s)
                #buffer empty:
                fail(b"", header, s)
                #invalid type:
                fail(None, header, s)

        #test very small sizes:
        for s in range(1, 10):
            cmp_unmask(b"".join(chr(i) for i in range(s+1+4)), 1, s)
        cmp_unmask(b"".join(chr(i) for i in range(9)), 1, 4)   #1+4+4=9
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
