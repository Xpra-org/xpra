# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The size limits of a native window (ie: win32's `MINMAXINFO`) are for the whole window, borders and title bar included,
in local pixels, whereas the server's size constraints are for the window contents, in server pixels.
"""

from collections.abc import Callable

from xpra.util.objects import typedict

Size = tuple[int, int]


def to_local_limit(scaling, limit: Size) -> Size:
    """
    Convert a size limit from server to local pixels, using the `sx`, `sy`, `cx` and `cy` methods of `scaling`
    (ie: the `display` subsystem).
    With fractional scaling, rounding the limit is not enough: at 0.2, 16384 server pixels round to 3277 local pixels,
    which convert back to 16385. Lower each dimension until it converts back to a size within the limit.
    """
    if not scaling:
        return limit

    def local_limit(value: int, to_local: Callable[[int], int], to_server: Callable[[int], int]) -> int:
        local = to_local(value)
        while local > 1 and to_server(local) > value:
            local -= 1
        return local

    w, h = limit
    return local_limit(w, scaling.sx, scaling.cx), local_limit(h, scaling.sy, scaling.cy)


def to_server_size(scaling, width: int, height: int, server_size: Size) -> Size:
    """
    Convert a window size to server pixels, using the `sx`, `sy`, `cx` and `cy` methods of `scaling`.
    With fractional scaling, several server sizes map to the same window size,
    and converting it back may not give the size the server knows:
    keep `server_size` on the axes where it still maps to the window size.
    """
    if not scaling:
        return width, height
    sw, sh = server_size
    if sw <= 0 or scaling.sx(sw) != width:
        sw = max(1, scaling.cx(width))
    if sh <= 0 or scaling.sy(sh) != height:
        sh = max(1, scaling.cy(height))
    return sw, sh


def get_track_sizes(size_constraints: typedict, max_window_size: Size, frame: Size,
                    to_local: Callable[[int, int], Size] | None = None,
                    fixed_size: Size | None = None) -> tuple[Size, Size]:
    """
    The minimum and maximum track sizes of the window, `0` means that there is no limit.
    `to_local` converts a size from server to local pixels,
    `max_window_size` is a hard limit in local pixels (the OpenGL windows lower it to the maximum texture size),
    and `frame` is the size of the borders and title bar.
    A `fixed_size`, in local pixels, replaces all the other limits (read-only mode).
    """
    if fixed_size:
        size = add_frame(fixed_size, frame)
        return size, size

    def local_size(name: str) -> Size:
        w, h = size_constraints.intpair(name)
        if w > 0 and h > 0 and to_local:
            return to_local(w, h)
        return w, h

    minw, minh = local_size("minimum-size")
    maxw, maxh = local_size("maximum-size")
    mww, mwh = max_window_size
    if mww > 0:
        maxw = min(maxw, mww) if maxw > 0 else mww
    if mwh > 0:
        maxh = min(maxh, mwh) if maxh > 0 else mwh
    return add_frame((minw, minh), frame), add_frame((maxw, maxh), frame)


def add_frame(size: Size, frame: Size) -> Size:
    w, h = size
    fw, fh = frame
    return (w + fw if w > 0 else 0), (h + fh if h > 0 else 0)
