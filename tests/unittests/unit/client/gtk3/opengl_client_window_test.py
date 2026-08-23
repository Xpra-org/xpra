#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 kogeler <25884155+kogeler@users.noreply.github.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.client.gtk3.opengl.client_window import GLClientWindowBase


class FakeBacking:

    def __init__(self) -> None:
        self.paint_screen = False
        self.presented = False

    def draw_fbo(self, context) -> object:
        assert self.paint_screen
        self.presented = True
        return context


class FakeWindow:

    def __init__(self, backing: FakeBacking | None, mapped: bool = True) -> None:
        self._backing = backing
        self.mapped = mapped

    def get_mapped(self) -> bool:
        return self.mapped


class OpenGLClientWindowTest(unittest.TestCase):

    def test_mapped_draw_enables_screen_paint_before_presenting(self) -> None:
        backing = FakeBacking()
        window = FakeWindow(backing)
        context = object()

        result = GLClientWindowBase.draw_widget(window, object(), context)

        self.assertIs(result, context)
        self.assertTrue(backing.paint_screen)
        self.assertTrue(backing.presented)

    def test_unmapped_draw_does_not_enable_screen_paint(self) -> None:
        backing = FakeBacking()
        window = FakeWindow(backing, mapped=False)

        result = GLClientWindowBase.draw_widget(window, object(), object())

        self.assertFalse(result)
        self.assertFalse(backing.paint_screen)
        self.assertFalse(backing.presented)


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
