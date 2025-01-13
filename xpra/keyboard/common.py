# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.str_fn import csv


class KeyEvent:
    __slots__ = ("modifiers", "keyname", "keyval", "keycode", "group", "string", "pressed")

    def __init__(self):
        self.modifiers: list[str] = []
        self.keyname: str = ""
        self.keyval: int = 0
        self.keycode: int = 0
        self.group: int = 0
        self.string: str = ""
        self.pressed: bool = True

    def __repr__(self):
        strattrs = csv(f"{k}="+str(getattr(self, k)) for k in KeyEvent.__slots__)
        return f"KeyEvent({strattrs})"
