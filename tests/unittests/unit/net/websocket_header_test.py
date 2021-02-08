#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.websockets.header import encode_hybi_header, decode_hybi
from xpra.log import Logger

log = Logger("network")


class WebsocketHeaderTest(unittest.TestCase):

    def test_round_trip(self):
        def rt(opcode, payload, has_mask=False, fin=True):
            h = encode_hybi_header(opcode, len(payload), has_mask, fin)
            packet = h+payload
            ropcode, rpayload, rlen, rfin = decode_hybi(packet)
            assert opcode==ropcode
            assert rpayload==payload
            assert rlen>len(payload)
            assert fin==rfin
        for l in (0, 10, 125, 126, 65535, 65536):
            rt(0, b"\0"*l)


    def test_invalid_decode(self):
        for l in (0, 10, 125, 126, 65535, 65536):
            for has_mask in (True, False):
                payload = b"\0"*l
                h = encode_hybi_header(0, len(payload), has_mask, True)
                if has_mask:
                    packet = h+b"9"*4+payload
                else:
                    packet = h+payload
                v = decode_hybi(packet)
                assert v
                v = decode_hybi(packet[:-1])
                assert v is None
                v = decode_hybi(packet[:int(has_mask)*4])
                assert v is None, "got %s" % (v,)
                if l>0:
                    for i in range(5):
                        v = decode_hybi(packet[:int(has_mask)*4+i])
                        assert v is None, "got %s" % (v,)

def main():
    unittest.main()


if __name__ == '__main__':
    main()
