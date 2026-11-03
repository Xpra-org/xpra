#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.gtk.keymap import get_gtk_keymap
from unit.process_test_util import DisplayContext


class TestKeymap(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(DisplayContext())

    def test_get_gtk_keymap(self):
        self.assertTrue(get_gtk_keymap())


def main():
    unittest.main()


if __name__ == '__main__':
    main()
