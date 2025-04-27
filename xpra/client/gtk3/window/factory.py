# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.util.env import envbool


def get_window_base_classes() -> tuple[type, ...]:
    from xpra.client.gtk3.window.base import GTKClientWindowBase
    WINDOW_BASES: list[type] = [GTKClientWindowBase]
    DRAGNDROP = envbool("XPRA_DRAGNDROP", True)
    if DRAGNDROP:
        from xpra.client.gtk3.window.dragndrop import DragNDropWindow
        WINDOW_BASES.append(DragNDropWindow)
    FOCUS = envbool("XPRA_FOCUS", True)
    if FOCUS:
        from xpra.client.gtk3.window.focus import FocusWindow
        WINDOW_BASES.append(FocusWindow)
    GRAB = envbool("XPRA_GRAB", True)
    if GRAB:
        from xpra.client.gtk3.window.grab import GrabWindow
        WINDOW_BASES.append(GrabWindow)
    return tuple(WINDOW_BASES)
