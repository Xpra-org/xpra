# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.log import Logger

log = Logger("x11", "server", "pointer")


class NoPointerDevice:
    __slots__ = ()

    def __repr__(self):
        return "NoPointerDevice"

    @staticmethod
    def move_pointer(x: int, y: int, props: dict) -> None:
        log("nopointer.move_pointer%s", (x, y, props))

    @staticmethod
    def get_position() -> tuple[int, int]:
        return 0, 0

    @staticmethod
    def click(position: Sequence[int], button: int, pressed: bool, props: dict) -> None:
        log("nopointer.click(%i, %s, %s)", button, pressed, props)

    @staticmethod
    def wheel_motion(button: int, distance: float) -> None:
        raise NotImplementedError()

    @staticmethod
    def has_precise_wheel() -> bool:
        return False
