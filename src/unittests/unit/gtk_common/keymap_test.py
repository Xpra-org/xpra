#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.os_util import POSIX
from xpra.gtk_common.keymap import get_gtk_keymap, do_get_gtk_keymap


class TestKeymap(unittest.TestCase):

    def test_get_gtk_keymap(self):
        assert not do_get_gtk_keymap(None, ())
        if not POSIX or os.environ.get("DISPLAY"):
            assert get_gtk_keymap()


def main():
    unittest.main()

if __name__ == '__main__':
    main()
