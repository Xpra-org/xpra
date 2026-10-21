#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.util import parsing
from xpra.util.parsing import r4cmp, fequ, scaleup_value, scaledown_value, parse_scaling, SCALING_OPTIONS, TRUE_OPTIONS


class TestVersionUtilModule(unittest.TestCase):

    def test_cmp(self):
        assert r4cmp(1) == 1000
        assert r4cmp(0) == 0
        assert r4cmp(0.5) == 500
        assert r4cmp(0.001) == 1
        assert r4cmp(0.0001) == 0
        for i in (-1, 0, 1, 10, 2 ** 24, 0.5, 0.001):
            assert fequ(i, i)
        assert fequ(0.001, 0.0014)
        assert not fequ(0.001, 0.002)

    def test_scaleupdown(self):
        l = len(SCALING_OPTIONS)
        assert l
        minv = min(SCALING_OPTIONS)
        maxv = max(SCALING_OPTIONS)
        for i, v in enumerate(SCALING_OPTIONS):
            up = scaleup_value(v)
            down = scaledown_value(v)
            assert v not in up
            assert v not in down
            if v == minv:
                assert not down
            if v == maxv:
                assert not up

    def test_parse_scaling(self):
        for v in TRUE_OPTIONS:
            assert parse_scaling(str(v), 100, 100) == (1, 1)

        def t(arg, expected) -> None:
            scaling = parse_scaling(arg, 100, 100)
            assert scaling == expected, f"expected {arg} but got {scaling}"

        t("50%", (0.5, 0.5))

    def test_automatic_scaling_thresholds(self):
        for width, height, expected in (
                (3960, 2160, 1), (7680, 4320, 1.25), (8192, 8192, 1.5),
                (16384, 16384, 5 / 3), (32768, 32768, 2), (65536, 65536, 4)):
            with self.subTest(size=(width, height)):
                self.assertEqual(parse_scaling("auto", width, height), (expected, expected))

    def test_custom_automatic_scaling(self):
        cases = (
            ("auto:100x100:1,200x200:1.5x2", 150, 150, (1.5, 2)),
            ("auto:100x100:1,200x200:1.5*2", 150, 150, (1.5, 2)),
            ("auto:100x100:1", 200, 200, (1, 1)),
            ("auto:bad,100x100:1x2x3,200x200:1.5", 150, 150, (1.5, 1.5)),
            ("auto-invalid", 100, 100, (1, 1)),
        )
        with patch.object(parsing, "Logger"):
            for value, width, height, expected in cases:
                with self.subTest(value=value):
                    self.assertEqual(parse_scaling(value, width, height), expected)

    def test_fixed_scaling_forms_and_absolute_dimensions(self):
        for value, expected in (
                ("2", (2, 2)), ("1.5", (1.5, 1.5)), ("3/2", (1.5, 1.5)), ("3:2", (1.5, 1.5)),
                ("1.5x2", (1.5, 2)), ("150%,200%", (1.5, 2)), ("1920x1080", (0.5, 0.5))):
            with self.subTest(value=value):
                self.assertEqual(parse_scaling(value, 3840, 2160), expected)

    def test_invalid_scaling_and_explicit_bounds(self):
        with patch.object(parsing, "Logger"):
            for value in ("no", "off", "0", "-1", "1/0", "bad", "1xbad", "100x100:1", "0.01", "999999"):
                with self.subTest(value=value):
                    self.assertEqual(parse_scaling(value, 1920, 1080), (1, 1))
            self.assertEqual(parse_scaling("0.5x2", 1920, 1080, min_scaling=0.5, max_scaling=2), (0.5, 2))
            self.assertEqual(parse_scaling("0.4", 1920, 1080, min_scaling=0.5, max_scaling=2), (1, 1))

    def test_refresh_delay_is_clamped(self):
        with patch.object(parsing, "Logger"):
            self.assertEqual(parsing.clamp_refresh_delay(0), parsing.MIN_REFRESH_DELAY)
            self.assertEqual(parsing.clamp_refresh_delay(parsing.MAX_REFRESH_DELAY + 1), parsing.MAX_REFRESH_DELAY)
            self.assertEqual(parsing.clamp_refresh_delay(parsing.MIN_REFRESH_DELAY), parsing.MIN_REFRESH_DELAY)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
