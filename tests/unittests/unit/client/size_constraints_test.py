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
from types import SimpleNamespace

from xpra.util.objects import typedict
from xpra.client.gui.size_constraints import get_track_sizes, to_local_limit

FRAME = (16, 39)


def double(w: int, h: int) -> tuple[int, int]:
    return w * 2, h * 2


def scaling(xscale: float, yscale: float):
    return SimpleNamespace(sx=lambda v: round(v * xscale), sy=lambda v: round(v * yscale),
                           cx=lambda v: round(v / xscale), cy=lambda v: round(v / yscale))


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

    def test_to_local_limit(self) -> None:
        limit = 16384, 16384
        self.assertEqual(to_local_limit(None, limit), limit)
        for xscale, yscale, expected in (
            (1, 1, (16384, 16384)),
            # 16384 rounds to 3277 and 6554, which convert back to 16385:
            (0.2, 0.2, (3276, 3276)),
            (0.4, 0.4, (6553, 6553)),
            (0.25, 0.5, (4096, 8192)),
            (0.8, 2, (13107, 32768)),
            (0.2, 1, (3276, 16384)),
        ):
            with self.subTest(xscale=xscale, yscale=yscale):
                self.assertEqual(to_local_limit(scaling(xscale, yscale), limit), expected)

    def test_to_local_limit_round_trip(self) -> None:
        # no size within the local limit converts back to more than the limit:
        for limit in (8192, 16384, 32768):
            for i in range(10, 301):
                scale = i / 100
                s = scaling(scale, scale)
                w, h = to_local_limit(s, (limit, limit))
                with self.subTest(limit=limit, scale=scale):
                    self.assertLessEqual(s.cx(w), limit)
                    self.assertLessEqual(s.cy(h), limit)
                    # and it is not lower than it has to be:
                    self.assertGreaterEqual(w, int(limit * scale))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
