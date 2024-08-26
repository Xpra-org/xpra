#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.gtk.keymap import get_gtk_keymap


class TestKeymap(unittest.TestCase):

    def test_get_gtk_keymap(self):
        assert get_gtk_keymap()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
