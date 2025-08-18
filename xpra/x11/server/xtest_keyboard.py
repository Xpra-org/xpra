# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Sequence

from xpra.x11.error import xsync, xlog
from xpra.x11.xkbhelper import clean_keyboard_state
from xpra.x11.bindings.test import XTestBindings
from xpra.x11.bindings.keyboard import X11KeyboardBindings
from xpra.log import Logger

log = Logger("x11", "server", "keyboard")

XTest = XTestBindings()
X11Keyboard = X11KeyboardBindings()


class XTestKeyboardDevice:
    __slots__ = ("min_keycode", "max_keycode")

    def __init__(self):
        with xsync:
            self.min_keycode, self.max_keycode = X11KeyboardBindings().get_minmax_keycodes()

    def __repr__(self):
        return "XTestKeyboardDevice"

    def press_key(self, keycode: int, press: bool) -> None:
        log("press_key%s", (keycode, press))
        if keycode < self.min_keycode or keycode > self.max_keycode:
            return
        with xsync:
            XTest.xtest_fake_key(keycode, press)

    @staticmethod
    def set_keyboard_repeat(delay: int, interval: int) -> None:
        if delay > 0 and interval > 0:
            with xsync:
                X11Keyboard.set_key_repeat_rate(delay, interval)

    def clear_keys_pressed(self, keycodes: Sequence[int]) -> None:
        # clear all the keys we know about:
        if keycodes:
            log("clearing keys pressed: %s", keycodes)
            with xsync:
                for keycode in keycodes:
                    self.press_key(keycode, False)
        # this will take care of any remaining ones we are not aware of:
        # (there should not be any - but we want to be certain)
        clean_keyboard_state()

    @staticmethod
    def set_repeat_rate(delay: int, interval: int) -> None:
        with xlog:
            X11Keyboard.set_key_repeat_rate(delay, interval)

    @staticmethod
    def get_keycodes_down() -> Sequence[int]:
        with xlog:
            return X11Keyboard.get_keycodes_down()

    @staticmethod
    def get_layout_group() -> int:
        with xlog:
            return X11Keyboard.get_layout_group()
