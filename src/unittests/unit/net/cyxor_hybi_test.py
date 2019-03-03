#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
import unittest
import numpy

from xpra.os_util import memoryview_to_bytes, strtobytes
from xpra.util import repr_ellipsized

class Test_cyxor_hybi(unittest.TestCase):

    def test_sameresult(self):
        try:
            try:
                #websockify 0.8.0 and earlier:
                from websockify.websocket import WebSocketRequestHandler    #@UnusedImport
                numpy_unmask = WebSocketRequestHandler.unmask
            except ImportError:
                from websockify.websocket import WebSocket
                ws = WebSocket()
                def wsunmask(buf, hlen, length):
                    mask_key = buf[hlen:hlen+4]
                    payload = buf[hlen+4:(hlen+4+length)]
                    return ws._unmask(payload, mask_key)
                numpy_unmask = wsunmask
            from xpra.codecs.xor.cyxor import hybi_unmask
        except ImportError as e:
            print("Warning: cyxor_hybi test skipped because: %s" % (e,))
            return

        def do_cmp_unmask(buf, hlen, plen):
            c = memoryview_to_bytes(hybi_unmask(buf, hlen, plen))
            w = numpy_unmask(buf, hlen, plen)
            assert w==c, "expected %s got %s" % (
                repr_ellipsized(binascii.hexlify(w)),
                repr_ellipsized(binascii.hexlify(c)),
                )
        def cmp_unmask(buf_len, hlen, plen):
            buf = strtobytes("".join(chr(x%256) for x in range(buf_len)))
            do_cmp_unmask(buf, hlen, plen)

        #tiny 1 byte buffer
        for hlen in range(8):
            cmp_unmask(hlen+4+1, hlen, 1)
        #no header and small buffers:
        cmp_unmask(8, 0, 4)
        cmp_unmask(64, 0, 32)

        def fail(buf_len, hlen, plen):
            for backend, unmask_fn in (
                ("cython", hybi_unmask),
                ("numpy", numpy_unmask),
                ):
                try:
                    unmask_fn(buf_len, hlen, plen)
                except:
                    pass
                else:
                    raise Exception("%s umask should have failed for buffer of size %i with header=%i and packet len=%i" %
                                    (backend, buf_len, hlen, plen))
        for s in (1, 1024, 1024*1024):
            for header in range(1, 10):
                #buffer too small:
                fail(s+4+header-1, header, s)
                #buffer empty:
                fail(0, header, s)
                #invalid type:
                fail(None, header, s)

        #test very small sizes:
        for s in range(1, 10):
            cmp_unmask(s+1+4, 1, s)
        cmp_unmask(9, 1, 4)   #1+4+4=9
        cmp_unmask(10, 1, 5)   #1+5+4=10
        cmp_unmask(14, 0, 10)
        cmp_unmask(14, 1, 9)
        cmp_unmask(128, 0, 128-4)

        BUF_SIZE = 1024*1024
        try:
            buf = numpy.random.randint(256, size=BUF_SIZE, dtype='B')
            buf = buf.tobytes()
        except TypeError:
            buf = binascii.unhexlify("00803EA1FA0673B9")*(BUF_SIZE//4)
        do_cmp_unmask(buf, 1, 5)

        for offset in range(8):
            for div in range(8):
                for extra in range(8):
                    size = BUF_SIZE//2//(2**div)+extra
                    do_cmp_unmask(buf, offset, size)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
