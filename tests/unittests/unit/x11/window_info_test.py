#!/usr/bin/env python3

import unittest

from xpra.x11.window_info import window_info


class WindowInfoTest(unittest.TestCase):

    def test_no_window_is_not_looked_up(self):
        self.assertEqual(window_info(0), "None")


if __name__ == "__main__":
    unittest.main()
