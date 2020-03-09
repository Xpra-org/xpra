#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import POSIX, OSX


class FakeXineramaTest(unittest.TestCase):

    def test_find(self):
        from xpra.x11.fakeXinerama import find_libfakeXinerama
        assert find_libfakeXinerama()

    def test_config(self):
        from xpra.x11.fakeXinerama import save_fakeXinerama_config, cleanup_fakeXinerama
        ss = ()
        save_fakeXinerama_config(True, "", ss)
        cleanup_fakeXinerama()


def main():
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()

if __name__ == '__main__':
    main()
