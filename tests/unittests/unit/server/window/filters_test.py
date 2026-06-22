#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.server.window.filters import get_window_filter


class Window:
    def __init__(self, **properties):
        self.properties = properties

    def get_property(self, name):
        value = self.properties[name]
        if isinstance(value, Exception):
            raise value
        return value


class WindowFiltersTest(unittest.TestCase):

    def test_in_and_not_in(self):
        window = Window(role=42)
        include = get_window_filter("window", "role", "=", "42")
        exclude = get_window_filter("window", "role", "!=", "42")
        self.assertTrue(include.matches(window))
        self.assertFalse(exclude.matches(window))
        self.assertIn("role", repr(include))

    def test_failures_and_validation(self):
        self.assertFalse(get_window_filter("window", "role", "=", "x").matches(Window(role=RuntimeError("bad"))))
        for args in (("screen", "role", "=", "x"), ("window", "role", "~", "x")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                get_window_filter(*args)

    def test_parent_filter_metadata(self):
        window_filter = get_window_filter("window-parent", "title", "=", "parent")
        self.assertTrue(window_filter.recurse)


if __name__ == "__main__":
    unittest.main()
