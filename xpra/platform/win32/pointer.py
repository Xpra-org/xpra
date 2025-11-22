# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from ctypes import byref
from ctypes.wintypes import POINT

from xpra.platform.win32 import win32con
from xpra.platform.win32.common import SetPhysicalCursorPos, GetPhysicalCursorPos, mouse_event

NOEVENT = (0, 0)
BUTTON_EVENTS: dict[tuple[int, bool], tuple[int, int]] = {
    # (button,up-or-down)  : win-event-name
    (1, True): (win32con.MOUSEEVENTF_LEFTDOWN, 0),
    (1, False): (win32con.MOUSEEVENTF_LEFTUP, 0),
    (2, True): (win32con.MOUSEEVENTF_MIDDLEDOWN, 0),
    (2, False): (win32con.MOUSEEVENTF_MIDDLEUP, 0),
    (3, True): (win32con.MOUSEEVENTF_RIGHTDOWN, 0),
    (3, False): (win32con.MOUSEEVENTF_RIGHTUP, 0),
    (4, True): (win32con.MOUSEEVENTF_WHEEL, win32con.WHEEL_DELTA),
    (4, False): NOEVENT,
    (5, True): (win32con.MOUSEEVENTF_WHEEL, -win32con.WHEEL_DELTA),
    (5, False): NOEVENT,
    (6, True): (win32con.MOUSEEVENTF_HWHEEL, win32con.WHEEL_DELTA),
    (6, False): NOEVENT,
    (7, True): (win32con.MOUSEEVENTF_HWHEEL, -win32con.WHEEL_DELTA),
    (7, False): NOEVENT,
    (8, True): (win32con.MOUSEEVENTF_XDOWN, win32con.XBUTTON1),
    (8, False): (win32con.MOUSEEVENTF_XUP, win32con.XBUTTON1),
    (9, True): (win32con.MOUSEEVENTF_XDOWN, win32con.XBUTTON2),
    (9, False): (win32con.MOUSEEVENTF_XUP, win32con.XBUTTON2),
}


def move_pointer(x: int, y: int) -> None:
    SetPhysicalCursorPos(x, y)


def get_position() -> tuple[int, int]:
    pos = POINT()
    GetPhysicalCursorPos(byref(pos))  # NOSONAR
    return pos.x, pos.y


def click(x: int, y: int, button: int, pressed: bool) -> None:
    event = BUTTON_EVENTS.get((button, pressed))
    if event is None:
        from xpra.log import Logger
        log = Logger("pointer", "win32")
        log.warn("no matching event found for button=%s, pressed=%s", button, pressed)
        return
    elif event == NOEVENT:
        return
    dwFlags, dwData = event
    mouse_event(dwFlags, x, y, dwData, 0)


class Win32Pointer:
    __slots__ = ()

    def __repr__(self):
        return "Win32Pointer"

    @staticmethod
    def move_pointer(x: int, y: int, _props: dict) -> None:
        move_pointer(x, y)

    @staticmethod
    def get_position() -> tuple[int, int]:
        return get_position()

    @staticmethod
    def click(position: Sequence[int], button: int, pressed: bool, _props: dict) -> None:
        x, y = position[:2]
        click(x, y, button, pressed)

    @staticmethod
    def has_precise_wheel() -> bool:
        return False


def get_pointer_device():
    return Win32Pointer()
