# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from AppKit import NSEvent
import Quartz.CoreGraphics as CG

from xpra.log import Logger

log = Logger("osx", "pointer")


def get_position() -> tuple[int, int]:
    location = NSEvent.mouseLocation()
    return location.x, location.y


def move_pointer(x: int, y: int) -> None:
    CG.CGWarpMouseCursorPosition((x, y))


def click(x, y, button: int, pressed: bool):
    if button <= 3:
        # we should be using CGEventCreateMouseEvent
        # instead we clear previous clicks when a "higher" button is pressed... oh well
        event = [(x, y), 1, button]
        for i in range(button):
            event.append(i == (button - 1) and pressed)
        r = CG.CGPostMouseEvent(*event)
        log("CG.CGPostMouseEvent%s=%s", event, r)
        return
    if not pressed:
        # we don't simulate press/unpress
        # so just ignore unpressed events
        return
    wheel = (button - 2) // 2
    direction = 1 - (((button - 2) % 2) * 2)
    event = [wheel]
    for i in range(wheel):
        if i != (wheel - 1):
            event.append(0)
        else:
            event.append(direction)
    r = CG.CGPostScrollWheelEvent(*event)
    log("CG.CGPostScrollWheelEvent%s=%s", event, r)


class MacOSPointer:
    __slots__ = ()

    def __repr__(self):
        return "MacOSPointer"

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
    return MacOSPointer()
