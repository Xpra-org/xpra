#!/usr/bin/env python3
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
            wsdata = h + payload
            ropcode, rpayload, rlen, rfin = decode_hybi(wsdata)
            assert opcode == ropcode
            assert rpayload == payload
            assert rlen > len(payload)
            assert fin == rfin
        for l in (0, 10, 125, 126, 65535, 65536):
            rt(0, b"\0"*l)

    def test_invalid_decode(self):
        for l in (0, 10, 125, 126, 65535, 65536):
            for has_mask in (True, False):
                payload = b"\0"*l
                h = encode_hybi_header(0, len(payload), has_mask, True)
                if has_mask:
                    wsdata = h + b"9"*4 + payload
                else:
                    wsdata = h + payload
                v = decode_hybi(wsdata)
                assert v
                v = decode_hybi(wsdata[:-1])
                assert v is None
                v = decode_hybi(wsdata[:int(has_mask)*4])
                assert v is None, "got %s" % (v,)
                if l>0:
                    for i in range(5):
                        v = decode_hybi(wsdata[:int(has_mask)*4+i])
                        assert v is None, "got %s" % (v,)

    def test_invalid_opcode(self):
        self.assertRaises(ValueError, encode_hybi_header, 0xFF, 0)

    def test_mask(self):
        from xpra.net.websockets.mask import hybi_mask, hybi_unmask
        mask = b"\x12\x34\x56\x78"

        def ref(data: bytes) -> bytes:
            return bytes(c ^ mask[i & 0x3] for i, c in enumerate(data))

        # short payloads, at every alignment of the data pointer:
        for size in range(20):
            payload = bytes(range(1, size + 1))
            for padding in range(4):
                buf = bytearray(padding) + mask + payload
                self.assertEqual(bytes(hybi_unmask(memoryview(buf), padding, size)), ref(payload))
                if payload:
                    data = memoryview(bytearray(padding) + payload)[padding:]
                    self.assertEqual(bytes(hybi_mask(mask, data)), ref(payload))
        # the buffer must contain the mask and the payload:
        with self.assertRaises(ValueError):
            hybi_unmask(mask + b"abc", 0, 4)
        with self.assertRaises(ValueError):
            hybi_unmask(mask, 0, 2 ** 32)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
