#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The size limits of the native windows (ie: win32): the server's size constraints are for the window contents,
in server pixels, the native limits include the frame and are in local pixels.
"""

import unittest

from xpra.util.objects import typedict
from xpra.client.gui.size_constraints import get_track_sizes

FRAME = (16, 39)


def double(w: int, h: int) -> tuple[int, int]:
    return w * 2, h * 2


class SizeConstraintsTest(unittest.TestCase):

    def test_no_constraints(self) -> None:
        self.assertEqual(get_track_sizes(typedict(), (0, 0), FRAME), ((0, 0), (0, 0)))

    def test_frame(self) -> None:
        constraints = typedict({"minimum-size": (100, 50), "maximum-size": (800, 600)})
        self.assertEqual(get_track_sizes(constraints, (0, 0), FRAME), ((116, 89), (816, 639)))

    def test_scaling(self) -> None:
        constraints = typedict({"minimum-size": (100, 50), "maximum-size": (800, 600)})
        self.assertEqual(get_track_sizes(constraints, (0, 0), FRAME, double), ((216, 139), (1616, 1239)))

    def test_max_window_size(self) -> None:
        # a hard limit in local pixels, which wins over the server's request:
        constraints = typedict({"maximum-size": (800, 600)})
        self.assertEqual(get_track_sizes(constraints, (1000, 500), FRAME, double), ((0, 0), (1016, 539)))
        self.assertEqual(get_track_sizes(typedict(), (1000, 500), FRAME), ((0, 0), (1016, 539)))

    def test_fixed_size(self) -> None:
        # read-only mode: the local size, which replaces all the other limits
        constraints = typedict({"minimum-size": (100, 50), "maximum-size": (800, 600)})
        sizes = get_track_sizes(constraints, (1000, 500), FRAME, double, fixed_size=(300, 200))
        self.assertEqual(sizes, ((316, 239), (316, 239)))

    def test_invalid(self) -> None:
        constraints = typedict({"minimum-size": (100, ), "maximum-size": (1, 2, 3)})
        self.assertEqual(get_track_sizes(constraints, (0, 0), FRAME, double), ((0, 0), (0, 0)))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
