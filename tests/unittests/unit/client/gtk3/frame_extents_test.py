#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Test how the frame extents of the hidden frame request window are validated."""

import unittest
from unittest.mock import patch

from xpra.client.gtk3 import frame_extents


class FrameSizesTest(unittest.TestCase):

    def frame_sizes(self, extents):
        with (
            patch.object(frame_extents, "frame_request_window", object()),
            patch.object(frame_extents, "get_platform_frame_sizes", return_value={}),
            patch.object(frame_extents, "get_frame_extents", return_value={"frame": extents} if extents else {}),
            patch.object(frame_extents, "get_wm_name", return_value="test-wm"),
            patch.object(frame_extents, "first_time", return_value=False),
        ):
            return frame_extents.get_window_frame_sizes()

    def test_no_request_window(self) -> None:
        with patch.object(frame_extents, "get_platform_frame_sizes", return_value={"normal": (1, 2, 3, 4)}):
            self.assertEqual(frame_extents.get_window_frame_sizes(), {"normal": (1, 2, 3, 4)})

    def test_valid(self) -> None:
        self.assertEqual(self.frame_sizes((1, 2, 30, 4)), {"frame": (1, 2, 30, 4), "offset": (1, 30)})

    def test_eight_values(self) -> None:
        # some window managers send 8 values, the last 4 are the ones we want:
        self.assertEqual(self.frame_sizes((0, 0, 0, 0, 5, 6, 7, 8)), {"frame": (5, 6, 7, 8), "offset": (5, 7)})

    def test_invalid(self) -> None:
        self.assertEqual(self.frame_sizes(()), {})
        self.assertEqual(self.frame_sizes((1, 2, 3, 1000)), {})
        self.assertEqual(self.frame_sizes((1, 2, 3)), {})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
