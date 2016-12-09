#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import strtobytes, bytestostr, memoryview_to_bytes, OSEnvContext


class TestOSUtil(unittest.TestCase):

    def check(self, str_value):
        b = strtobytes(str_value)
        assert b
        s = bytestostr(b)
        assert s
        assert s==str_value
        if not memoryview:
            return
        mv = memoryview(b)
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

    def test_env_context(self):
        import os
        env = os.environ.copy()
        with OSEnvContext():
            os.environ["foo"] = "bar"
        assert os.environ.get("foo")!="bar"
        assert os.environ==env


def main():
    unittest.main()

if __name__ == '__main__':
    main()
