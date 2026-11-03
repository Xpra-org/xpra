# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The pointer packets of the minimal clients (pyglet, qt6 and tk),
which do not have a `pointer` subsystem.
"""

from collections.abc import Sequence


def split_position(position: Sequence[int]) -> tuple[tuple[int, int], dict]:
    """
    `(x_root, y_root, x, y)` to the pointer field of the packets: the position on the screen,
    and their properties: the position relative to the window, which the server prefers
    """
    x, y, wx, wy = position
    return (x, y), {"window-position": (wx, wy)}
