#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.os_util import load_binary_file
from xpra.x11.fakeXinerama import save_fakeXinerama_config, find_libfakeXinerama, cleanup_fakeXinerama

class FakeXineramaTest(unittest.TestCase):

    def test_find(self):
        assert find_libfakeXinerama()

    def test_config(self):
        ss = ()
        save_fakeXinerama_config(True, "", ss)
        cleanup_fakeXinerama()


def main():
    unittest.main()

if __name__ == '__main__':
    main()
