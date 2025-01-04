#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

# pylint: disable=import-outside-toplevel

class TestDisplayUtil(unittest.TestCase):

    def test_repr(self):
        from xpra.x11.common import X11Event, REPR_FUNCTIONS
        class Custom():  # pylint: disable=too-few-public-methods
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
        def f(s, find=True):
            if repr(e).find(s)>=0 == find:
                #print("repr=%s" % repr(e))
                raise ValueError(f"{s!r} in {e!r}: {not find}")
        f(name)
        f(f"{e.serial:x}")
        f(e.display, False)
        f(e.type, False)
        f("XXXXX", True)


def main():
    from xpra.os_util import POSIX, OSX
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()

if __name__ == '__main__':
    main()
