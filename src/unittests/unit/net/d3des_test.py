#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.d3des import generate_response, deskey, desfunc, decrypt_passwd

class TestD3DES(unittest.TestCase):

    def test_des(self):
        key = bytearray.fromhex('0123456789abcdef')
        plain = bytearray.fromhex('0123456789abcdef')
        cipher = bytearray.fromhex('6e09a37726dd560c')
        ek = deskey(key, False)
        dk = deskey(key, True)
        assert desfunc(plain, ek) == cipher
        assert desfunc(desfunc(plain, ek), dk) == plain
        assert desfunc(desfunc(plain, dk), ek) == plain

    def test_generate_response(self):
        challange = b"helloworld0123456789"[:16]
        for passwd in (b"", b"0"*32):
            r = generate_response(passwd, challange)
            assert r
        assert decrypt_passwd(b"helloworld"[:8])

def main():
    unittest.main()

if __name__ == '__main__':
    main()
