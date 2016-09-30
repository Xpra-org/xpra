#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import strtobytes, bytestostr, _memoryview, memoryview_to_bytes


class TestModuleFunctions(unittest.TestCase):

    def check(self, str_value):
        b = strtobytes(str_value)
        assert b
        s = bytestostr(b)
        assert s
        assert s==str_value
        if not _memoryview:
            return
        mv = _memoryview(b)
        mvb = memoryview_to_bytes(mv)
        mvs = bytestostr(mvb)
        assert mvs==str_value


    def test_strs(self):
        for l in (1, 16, 255):
            zeroes  = chr(0)*l
            ones    = chr(1)*l
            ff      = chr(255)*l
            fe      = chr(254)*l
            self.check(zeroes)
            self.check(ones)
            self.check(ff)
            self.check(fe)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
