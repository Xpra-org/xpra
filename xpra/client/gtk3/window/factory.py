# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.os_util import WIN32, OSX
from xpra.util.env import envbool


def get_window_base_classes() -> tuple[type, ...]:
    from xpra.client.gtk3.window.base import GTKClientWindowBase
    from xpra.client.gui.window.action import ActionWindow
    from xpra.client.gtk3.window.headerbar import HeaderBarWindow
    from xpra.client.base import features
    # headerbar could be toggled using a feature:
    WINDOW_BASES: list[type] = [GTKClientWindowBase, ActionWindow, HeaderBarWindow]
    DRAGNDROP = envbool("XPRA_DRAGNDROP", True)
    if features.file and DRAGNDROP:
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
    WORKSPACE = envbool("XPRA_WORKSPACE", True)
    if WORKSPACE:
        from xpra.client.gtk3.window.workspace import WorkspaceWindow
        WINDOW_BASES.append(WorkspaceWindow)
    XSHAPE = envbool("XPRA_XSHAPE", not (OSX or WIN32))
    if XSHAPE:
        from xpra.client.gtk3.window.shape import ShapeWindow
        WINDOW_BASES.append(ShapeWindow)
    if features.keyboard:
        from xpra.client.gtk3.window.keyboard import KeyboardWindow
        WINDOW_BASES.append(KeyboardWindow)
    if features.pointer:
        from xpra.client.gtk3.window.pointer import PointerWindow
        WINDOW_BASES.append(PointerWindow)
    return tuple(WINDOW_BASES)
