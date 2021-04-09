#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.net.ssh import (
    keymd5, get_default_keyfiles,
    )


class SSHTest(unittest.TestCase):

    def test_keymd5(self):
        k = AdHocStruct()
        k.get_fingerprint = lambda : b"abcd"
        assert keymd5(k).startswith("MD5:")

    def test_default_keyfiles(self):
        assert get_default_keyfiles()


def main():
    unittest.main()

if __name__ == '__main__':
    main()
