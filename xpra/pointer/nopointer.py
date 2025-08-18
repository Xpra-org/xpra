# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger

log = Logger("x11", "server", "pointer")


class NoPointerDevice:
    __slots__ = ()

    def __repr__(self):
        return "NoPointerDevice"

    @staticmethod
    def move_pointer(x: int, y: int, props: dict) -> None:
        log("xtest_fake_motion%s", (x, y, props))

    @staticmethod
    def click(button: int, pressed: bool, props: dict) -> None:
        log("xtest_fake_button(%i, %s, %s)", button, pressed, props)

    @staticmethod
    def has_precise_wheel() -> bool:
        return False
