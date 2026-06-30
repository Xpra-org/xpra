#!/usr/bin/env python3

import unittest
from unittest.mock import patch


class TestIconUtil(unittest.TestCase):

    def test_load_icon_from_xpm_failure_returns_empty(self):
        with patch("PIL.Image.open", side_effect=ValueError("decode failed")):
            from xpra.codecs.icon_util import load_icon_from_file
            icon = load_icon_from_file("/tmp/test-icon.xpm")

        self.assertEqual(icon, ())


def main():
    unittest.main()


if __name__ == "__main__":
    main()
