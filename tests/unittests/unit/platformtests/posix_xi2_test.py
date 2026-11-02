#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import POSIX, OSX


def has_xi2_bindings() -> bool:
    try:
        from xpra.x11.bindings import xi2
        assert xi2
    except ImportError:
        return False
    return True


@unittest.skipUnless(POSIX and not OSX and has_xi2_bindings(), "requires the X11 XI2 bindings")
class XI2WindowImportTest(unittest.TestCase):

    def test_import(self) -> None:
        # the client only imports this module once XI2 is enabled,
        # so a broken import would otherwise go unnoticed:
        from xpra.platform.posix.xi2 import XI2_Window
        self.assertTrue(callable(XI2_Window))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
