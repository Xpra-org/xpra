# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.x11.error import xsync
from xpra.x11.bindings.test import XTestBindings
from xpra.log import Logger

log = Logger("x11", "server", "pointer")


class XTestPointerDevice:
    __slots__ = ()

    def __repr__(self):
        return "XTestPointerDevice"

    @staticmethod
    def move_pointer(x: int, y: int, props: dict) -> None:
        log("xtest_fake_motion%s", (x, y, props))
        with xsync:
            XTestBindings().xtest_fake_motion(x, y)

    @staticmethod
    def get_position() -> tuple[int, int]:
        with xsync:
            from xpra.x11.bindings.keyboard import X11KeyboardBindings
            return X11KeyboardBindings().query_pointer()

    @staticmethod
    def click(position: Sequence[int], button: int, pressed: bool, props: dict) -> None:
        log("xtest_fake_button(%s, %i, %s, %s)", position, button, pressed, props)
        with xsync:
            XTestBindings().xtest_fake_button(button, pressed)

    @staticmethod
    def wheel_motion(button: int, distance: float) -> None:
        raise NotImplementedError()

    @staticmethod
    def has_precise_wheel() -> bool:
        return False
