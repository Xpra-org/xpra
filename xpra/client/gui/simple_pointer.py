# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The pointer packets of the minimal clients (pyglet, qt6 and tk),
which do not have a `pointer` subsystem.
"""

from time import monotonic
from collections.abc import Callable, Sequence

from xpra.net.packet_type import POINTER_MOTION, POINTER_BUTTON
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("mouse")

# the minimum delay between two motion packets, in milliseconds:
# (about the same as the pointer subsystem's automatic delay, at 60Hz)
MOTION_DELAY = envint("XPRA_MOUSE_DELAY", 5)

# without a device, the server ignores the sequence numbers:
DEVICE_ID = -1
SEQUENCE = 0


def split_position(position: Sequence[int]) -> tuple[tuple[int, int], dict]:
    """
    `(x_root, y_root, x, y)` to the pointer field of the packets: the position on the screen,
    and their properties: the position relative to the window, which the server prefers
    """
    x, y, wx, wy = position
    return (x, y), {"window-position": (wx, wy)}


class SimplePointer:
    """
    Sends the pointer events of all the windows of a client:
    * at most one motion packet every `MOTION_DELAY` milliseconds, the latest one
    * only the release of the buttons we have sent the press for
    """

    def __init__(self, send: Callable, timeout_add: Callable[[int, Callable], object], delay: int = MOTION_DELAY):
        self.send = send
        self.timeout_add = timeout_add
        self.delay = delay
        self.motion_time = 0.0
        self.motion_pending: tuple | None = None
        self.motion_timer = False
        self.buttons_pressed: set[int] = set()

    def motion(self, wid: int, position: Sequence[int]) -> None:
        pos, props = split_position(position)
        self.motion_pending = (wid, pos, props)
        if self.motion_timer:
            # it will be sent when the timer fires
            return
        delay = self.delay - int(1000 * (monotonic() - self.motion_time))
        if delay > 0:
            self.motion_timer = True
            self.timeout_add(delay, self.motion_timeout)
        else:
            self.send_motion()

    def motion_timeout(self) -> bool:
        self.motion_timer = False
        self.send_motion()
        # (don't run again)
        return False

    def send_motion(self) -> None:
        if not self.motion_pending:
            return
        wid, pos, props = self.motion_pending
        self.motion_pending = None
        self.motion_time = monotonic()
        self.send(POINTER_MOTION, DEVICE_ID, SEQUENCE, wid, pos, props)

    def button(self, wid: int, button: int, pressed: bool, position: Sequence[int]) -> None:
        if pressed == (button in self.buttons_pressed):
            # ie: the release of a button pressed before the window got the pointer,
            # or the release of the wheel buttons with pyglet
            log("ignoring %s of button %i", "press" if pressed else "release", button)
            return
        if pressed:
            self.buttons_pressed.add(button)
        else:
            self.buttons_pressed.discard(button)
        pos, props = split_position(position)
        # this packet updates the position, so any pending motion is redundant:
        self.motion_pending = None
        self.send(POINTER_BUTTON, DEVICE_ID, SEQUENCE, wid, button, pressed, pos, props)

    def click(self, wid: int, button: int, position: Sequence[int], count: int = 1) -> None:
        """ ie: the wheel, as clicks of the buttons 4 to 7 """
        for _ in range(count):
            self.button(wid, button, True, position)
            self.button(wid, button, False, position)

    def wheel(self, wid: int, dx: float, dy: float, position: Sequence[int]) -> None:
        """
        `dx` and `dy` in steps of the wheel: positive is right and up,
        sent as clicks of the wheel buttons: 4 and 5 for up and down, 6 and 7 for left and right
        """
        for button, value in ((4, dy), (6, -dx)):
            if value:
                if value < 0:
                    button += 1
                self.click(wid, button, position, max(1, round(abs(value))))
