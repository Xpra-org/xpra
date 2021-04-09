#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest



class TestDisplayUtil(unittest.TestCase):

    def test_repr(self):
        from xpra.x11.common import X11Event, REPR_FUNCTIONS
        class Custom():
            def repr(self):
                return "Custom"
        def custom_repr(*_args):
            return "XXXXX"
        REPR_FUNCTIONS[Custom] = custom_repr
        name = "00name00"
        e = X11Event(name)
        e.display = "00display00"
        e.type = "00type00"
        e.serial = 255
        e.custom = Custom()
        assert repr(e).find(name)>0
        assert repr(e).find(e.display)<0
        assert repr(e).find(e.type)<0
        assert repr(e).find("%#x" % e.serial)>0
        assert repr(e).find("XXXXX")>0


def main():
    from xpra.os_util import POSIX, OSX
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()

if __name__ == '__main__':
    main()
