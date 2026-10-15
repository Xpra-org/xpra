# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the GNU GPL v2, or (at your option) any later version.
# See the file COPYING for the license information.

"""
On layouts that have an `AltGr` key (ie: German), Windows reports it as `Control`+`Alt`:
it injects a fake left `Control` key event right before the right `Alt` key event,
for presses, releases and every autorepeat.
Both events share the same message time, which is how we tell them apart from
a real `Control` key, the same way Chromium and Firefox do.
"""

from typing import NamedTuple

import win32con

# bit 24 of `lparam` is the extended key flag,
# it tells the right hand side keys apart from the left hand side ones:
EXTENDED_FLAG = 1 << 24

KEY_DOWN_MESSAGES = (win32con.WM_KEYDOWN, win32con.WM_SYSKEYDOWN)

# the keyboard layouts on which we have seen `AltGr` emit a fake `Control`:
altgr_layouts: set[int] = set()


class KeyMessage(NamedTuple):
    message: int
    vk_code: int
    lparam: int
    time: int

    def is_down(self) -> bool:
        return self.message in KEY_DOWN_MESSAGES

    def is_extended(self) -> bool:
        return bool(self.lparam & EXTENDED_FLAG)


def is_altgr_fake_control(key: KeyMessage, other: KeyMessage | None) -> bool:
    """
    `other` is the key message right before or right after `key`:
    `key` is the fake `Control` if `other` is the right `Alt` key
    going in the same direction at the same time.
    """
    if not other:
        return False
    if key.vk_code != win32con.VK_CONTROL or key.is_extended():
        return False
    if other.vk_code != win32con.VK_MENU or not other.is_extended():
        return False
    return key.is_down() == other.is_down() and key.time == other.time


def add_altgr_layout(hkl: int) -> None:
    altgr_layouts.add(hkl)


def has_altgr(hkl: int) -> bool:
    return hkl in altgr_layouts


def get_alt_r_keyname(hkl: int) -> str:
    # the right hand side `Alt` key is `AltGr` on most non-US layouts:
    return "ISO_Level3_Shift" if has_altgr(hkl) else "Alt_R"
