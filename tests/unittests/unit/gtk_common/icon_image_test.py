#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import gi_import
from xpra.gtk.widget import icon_image
from unit.process_test_util import DisplayContext

Gtk = gi_import("Gtk")


class IconImageTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(DisplayContext())

    def test_icon(self) -> None:
        image = icon_image("xpra.png")
        self.assertIsInstance(image, Gtk.Image)
        self.assertGreater(image.get_pixbuf().get_width(), 16)

    def test_scaled(self) -> None:
        image = icon_image("xpra.png", 16)
        self.assertEqual((image.get_pixbuf().get_width(), image.get_pixbuf().get_height()), (16, 16))

    def test_missing(self) -> None:
        self.assertIsNone(icon_image(""))
        self.assertIsNone(icon_image("this-icon-does-not-exist.png"))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
