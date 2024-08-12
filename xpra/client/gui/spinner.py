#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

class cv:
    trs: tuple[tuple[float, float, float, float, float, float, float, float]] = (
        (0.00, 0.15, 0.30, 0.50, 0.65, 0.80, 0.90, 1.00),
        (1.00, 0.00, 0.15, 0.30, 0.50, 0.65, 0.80, 0.90),
        (0.90, 1.00, 0.00, 0.15, 0.30, 0.50, 0.65, 0.80),
        (0.80, 0.90, 1.00, 0.00, 0.15, 0.30, 0.50, 0.65),
        (0.65, 0.80, 0.90, 1.00, 0.00, 0.15, 0.30, 0.50),
        (0.50, 0.65, 0.80, 0.90, 1.00, 0.00, 0.15, 0.30),
        (0.30, 0.50, 0.65, 0.80, 0.90, 1.00, 0.00, 0.15),
        (0.15, 0.30, 0.50, 0.65, 0.80, 0.90, 1.00, 0.00)
    )

    SPEED = 100
    CLIMIT = 1000
    NLINES = 8
