# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.error import xsync
from xpra.x11.bindings.core import X11CoreBindings, get_root_xid
from xpra.x11.bindings.test import XTestBindings
from xpra.x11.bindings.window import X11WindowBindings
from xpra.log import Logger

log = Logger("x11", "server", "pointer")


class XTestPointerDevice:
    __slots__ = ("multi_screen", )

    def __init__(self):
        # the screen count never changes for a given display connection,
        # so only multi-screen displays pay for the extra `XQueryPointer` round-trip:
        self.multi_screen = X11CoreBindings().get_screen_count() > 1

    def __repr__(self):
        return "XTestPointerDevice"

    def move_pointer(self, x: int, y: int, props: dict) -> None:
        log("xtest_fake_motion%s", (x, y, props))
        with xsync:
            if self.multi_screen and not X11CoreBindings().is_pointer_on_screen():
                # XTest motion events stay on the screen the pointer is currently on,
                # so warp it to our screen first:
                log("pointer is on another screen, warping it to %s", (x, y))
                X11WindowBindings().XWarpPointer(0, get_root_xid(), 0, 0, 0, 0, x, y)
            XTestBindings().xtest_fake_motion(x, y)

    # noinspection PyInconsistentReturns
    @staticmethod
    def get_position() -> tuple[int, int]:
        with xsync:
            from xpra.x11.bindings.keyboard import X11KeyboardBindings
            return X11KeyboardBindings().query_pointer()

    @staticmethod
    def click(button: int, pressed: bool, props: dict) -> None:
        log("xtest_fake_button(%i, %s, %s)", button, pressed, props)
        with xsync:
            XTestBindings().xtest_fake_button(button, pressed)

    @staticmethod
    def wheel_motion(button: int, distance: float) -> None:
        raise NotImplementedError()

    @staticmethod
    def has_precise_wheel() -> bool:
        return False
