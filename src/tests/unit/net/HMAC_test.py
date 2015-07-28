#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import hmac
import hashlib
import unittest

class TestHMAC(unittest.TestCase):

    def test_hardcoded(self):
        password = b"71051d81d27745b59c1c56c6e9046c19697e452453e04aa5abbd52c8edc8c232"
        salt = b"99ea464f-7117-4e38-95b3-d3aa80e7b806"
        hmac_hash = hmac.HMAC(password, salt, digestmod=hashlib.md5)
        hd = hmac_hash.hexdigest()
        ed = "dc26a074c9378b1b5735a27563320a26"
        assert hd == ed, "expected digest %s but got %s" % (ed, hd)

def main():
    unittest.main()

if __name__ == '__main__':
    main()
