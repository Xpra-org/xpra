#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.parsing import r4cmp, fequ, scaleup_value, scaledown_value, parse_scaling, SCALING_OPTIONS
from xpra.scripts.config import TRUE_OPTIONS


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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
