#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import TypeAlias
from math import pi, sin, cos

POS: TypeAlias = tuple[float, float]
NLINES = 8


def pos(pct: int, degree: float) -> POS:
    return sin(degree) * pct / 100, cos(degree) * pct / 100


def gen_trapezoids(inner_pct=20, outer_pct=70) -> list[tuple[POS, POS, POS, POS]]:
    step = 2 * pi / NLINES
    traps = []
    for i in range(NLINES):
        deg = i * step
        # each trapezoid has 4 coordinates:
        inner_left = pos(inner_pct, deg)
        inner_right = pos(inner_pct, deg + step / 2)
        outer_left = pos(outer_pct, deg)
        outer_right = pos(outer_pct, deg + step / 2)
        traps.append((inner_left, inner_right, outer_left, outer_right))
    return traps
