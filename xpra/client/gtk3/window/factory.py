# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_window_base_classes() -> tuple[type, ...]:
    from xpra.client.gtk3.window.base import GTKClientWindowBase
    WINDOW_BASES: list[type] = [GTKClientWindowBase]
    return tuple(WINDOW_BASES)
