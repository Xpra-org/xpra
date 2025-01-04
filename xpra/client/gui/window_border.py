# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.common import Self


class WindowBorder:

    def __init__(self, shown: bool = True,
                 red: float = 0.9, green: float = 0.1, blue: float = 0.1, alpha: float = 0.6, size: int = 4):
        self.shown: bool = shown
        self.red: float = red
        self.green: float = green
        self.blue: float = blue
        self.alpha: float = alpha
        self.size: int = size

    def toggle(self) -> None:
        self.shown = not self.shown

    def clone(self) -> Self:
        return WindowBorder(self.shown, self.red, self.green, self.blue, self.alpha, self.size)

    def __repr__(self):
        def hex2(v):
            b = int(max(0, min(255, v * 256)))
            if b < 16:
                return f"0{b:X}"
            return f"{b:X}"

        return "WindowBorder(%s, 0x%s%s%s, %s, %s)" % (
            self.shown,
            hex2(self.red), hex2(self.green), hex2(self.blue), self.alpha, self.size,
        )
