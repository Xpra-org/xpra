# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
xpra's window menu items, added to the native system menu of each window
(shown by `Alt`+`Space`, a right click on the title bar, or the `show_window_menu` shortcut)
"""

import win32con
from ctypes import byref
from ctypes.wintypes import POINT
from collections.abc import Sequence

from xpra.platform.win32.common import (
    GetSystemMenu, AppendMenuW, CheckMenuItem, CreatePopupMenu, DestroyMenu, TrackPopupMenu, GetCursorPos,
)
from xpra.log import Logger

log = Logger("menu")

# `WM_SYSCOMMAND` ids must be below `0xF000` (the `SC_*` commands),
# with the low 4 bits clear since the system uses those internally.
# (id, label, shortcut action, state key for a checkbox item or "")
SYSTEM_MENU_ITEMS: Sequence[tuple[int, str, str, str]] = (
    (0x1000, "Window Information", "show_window_info", ""),
    (0x1010, "Fullscreen", "toggle_fullscreen", "fullscreen"),
    (0x1020, "Always on Top", "toggle_above", "above"),
    (0x1030, "Grab Keyboard", "toggle_keyboard_grab", "keyboard-grab"),
    (0x1040, "Grab Pointer", "toggle_pointer_grab", "pointer-grab"),
    (0x1050, "Show Border", "magic_key", "border"),
    (0x1060, "Refresh", "refresh_window", ""),
)

SYSTEM_MENU_ACTIONS: dict[int, str] = {item[0]: item[2] for item in SYSTEM_MENU_ITEMS}


def get_command_action(wparam: int) -> str:
    # the shortcut action for a `WM_SYSCOMMAND` `wparam`, if it is one of ours:
    return SYSTEM_MENU_ACTIONS.get(wparam & 0xFFF0, "")


def append_items(menu: int, border: bool) -> None:
    for item_id, text, _action, state in SYSTEM_MENU_ITEMS:
        if state == "border" and not border:
            continue
        AppendMenuW(menu, win32con.MF_STRING, item_id, text)


def add_system_menu_items(hwnd: int, border: bool) -> None:
    """
    `border` is only useful for windows that can render it (OpenGL)
    """
    menu = GetSystemMenu(hwnd, False)
    log("add_system_menu_items(%#x, %s) system menu=%#x", hwnd, border, menu or 0)
    if not menu:
        return
    AppendMenuW(menu, win32con.MF_SEPARATOR, 0, None)
    append_items(menu, border)


def update_checks(menu: int, states: dict[str, bool]) -> None:
    for item_id, _text, _action, state in SYSTEM_MENU_ITEMS:
        if state:
            check = win32con.MF_CHECKED if states.get(state) else win32con.MF_UNCHECKED
            CheckMenuItem(menu, item_id, win32con.MF_BYCOMMAND | check)


def popup_menu(hwnd: int, border: bool, states: dict[str, bool]) -> str:
    """
    Show xpra's items in a popup menu at the pointer position,
    for windows without a system menu (ie: undecorated).
    Returns the action selected, if any.
    """
    menu = CreatePopupMenu()
    if not menu:
        return ""
    try:
        append_items(menu, border)
        update_checks(menu, states)
        pos = POINT()
        GetCursorPos(byref(pos))
        # `TrackPopupMenu` runs a modal loop, which the window procedure services
        # via its `WM_ENTERMENULOOP` / `WM_EXITMENULOOP` handlers:
        cmd = TrackPopupMenu(menu, win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON, pos.x, pos.y, 0, hwnd, None)
        log("TrackPopupMenu(..)=%s", cmd)
        return SYSTEM_MENU_ACTIONS.get(cmd, "")
    finally:
        DestroyMenu(menu)
