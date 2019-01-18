#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import numpy
import unittest

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
        def cython_unmask(buf, hlen, plen):
            pstart = hlen + 4
            pend = pstart + plen
            mask = buf[hlen:hlen+4]
            data = buf[pstart:pend]
            return hybi_unmask(mask, data)

        def cmp_unmask(buf, hlen, plen):
            c = cython_unmask(buf, hlen, plen)
            w = WebSocketRequestHandler.unmask(buf, hlen, plen)
            assert c==w
        
        BUF_SIZE = 1024*1024
        buf = numpy.random.randint(256, size=BUF_SIZE, dtype='B')
        buf = buf.tobytes()
        for offset in range(8):
            for div in range(8):
                for extra in range(8):
                    size = BUF_SIZE//2//(2**div)+extra
                    cmp_unmask(buf, offset, size)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
