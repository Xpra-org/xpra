# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from AppKit import NSEvent
import Quartz.CoreGraphics as CG

from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("osx", "pointer")

POSTMOUSEEVENT = envbool("XPRA_MACOS_POSTMOUSEEVENT", False)
POSTSCROLLWHEELEVENT = envbool("XPRA_MACOS_POSTSCROLLWHEELEVENT", False)

# maps an xpra button (1=left, 2=middle, 3=right) to the
# macOS event type (down, up) and the CGMouseButton for CGEventCreateMouseEvent:
BUTTON_EVENTS = {
    1: (CG.kCGEventLeftMouseDown, CG.kCGEventLeftMouseUp, CG.kCGMouseButtonLeft),
    2: (CG.kCGEventOtherMouseDown, CG.kCGEventOtherMouseUp, CG.kCGMouseButtonCenter),
    3: (CG.kCGEventRightMouseDown, CG.kCGEventRightMouseUp, CG.kCGMouseButtonRight),
}


def get_position() -> tuple[int, int]:
    location = NSEvent.mouseLocation()
    return round(location.x), round(location.y)


def move_pointer(x: int, y: int) -> None:
    CG.CGWarpMouseCursorPosition((x, y))


def post_mouse_event(x, y, button: int, pressed: bool) -> None:
    # legacy CGPostMouseEvent: takes the state of all buttons at once,
    # so we clear previous clicks when a "higher" button is pressed... oh well
    event = [(x, y), 1, button]
    for i in range(button):
        event.append(i == (button - 1) and pressed)
    r = CG.CGPostMouseEvent(*event)
    log("CG.CGPostMouseEvent%s=%s", event, r)


def create_mouse_event(x, y, button: int, pressed: bool) -> None:
    down, up, mouse_button = BUTTON_EVENTS[button]
    evtype = down if pressed else up
    event = CG.CGEventCreateMouseEvent(None, evtype, (x, y), mouse_button)
    r = CG.CGEventPost(CG.kCGHIDEventTap, event)
    log("CG.CGEventCreateMouseEvent(None, %s, %s, %s) post=%s", evtype, (x, y), mouse_button, r)


def get_wheel_deltas(button: int) -> list[int]:
    # buttons 4/5 scroll the first wheel (vertical), 6/7 the second (horizontal), etc.
    # only the last axis carries the direction (+1 / -1), the others are left at 0
    wheel = (button - 2) // 2
    direction = 1 - (((button - 2) % 2) * 2)
    return [direction if i == (wheel - 1) else 0 for i in range(wheel)]


def post_scroll_wheel_event(button: int) -> None:
    deltas = get_wheel_deltas(button)
    event = [len(deltas)] + deltas
    r = CG.CGPostScrollWheelEvent(*event)
    log("CG.CGPostScrollWheelEvent%s=%s", event, r)


def create_scroll_wheel_event(button: int) -> None:
    deltas = get_wheel_deltas(button)
    event = CG.CGEventCreateScrollWheelEvent(None, CG.kCGScrollEventUnitLine, len(deltas), *deltas)
    r = CG.CGEventPost(CG.kCGHIDEventTap, event)
    log("CG.CGEventCreateScrollWheelEvent(None, line, %s, %s) post=%s", len(deltas), deltas, r)


def click(x, y, button: int, pressed: bool):
    if button <= 3:
        if POSTMOUSEEVENT:
            post_mouse_event(x, y, button, pressed)
        else:
            create_mouse_event(x, y, button, pressed)
        return
    if not pressed:
        # we don't simulate press/unpress
        # so just ignore unpressed events
        return
    if POSTSCROLLWHEELEVENT:
        post_scroll_wheel_event(button)
    else:
        create_scroll_wheel_event(button)


class MacOSPointer:
    __slots__ = ("position",)

    def __init__(self):
        self.position = 0, 0

    def __repr__(self):
        return "MacOSPointer"

    def move_pointer(self, x: int, y: int, _props: dict) -> None:
        self.position = x, y
        move_pointer(x, y)

    @staticmethod
    def get_position() -> tuple[int, int]:
        return get_position()

    def click(self, button: int, pressed: bool, _props: dict) -> None:
        x, y = self.position
        click(x, y, button, pressed)

    @staticmethod
    def has_precise_wheel() -> bool:
        return False


def get_pointer_device():
    return MacOSPointer()
