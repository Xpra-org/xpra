# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

class WindowBorder:

    def __init__(self, shown=True, red=0.9, green=0.1, blue=0.1, alpha=0.6, size=4):
        self.shown = shown
        self.red = red
        self.green = green
        self.blue = blue
        self.alpha = alpha
        self.size = size

    def toggle(self):
        self.shown = not self.shown

    def clone(self):
        return WindowBorder(self.shown, self.red, self.green, self.blue, self.alpha, self.size)

    def __repr__(self):
        def hex2(v):
            b = int(max(0, min(255, v*256)))
            if b<16:
                return "0%X" % b
            return "%X" % b
        return "WindowBorder(%s, 0x%s%s%s, %s, %s)" % (self.shown, hex2(self.red), hex2(self.green), hex2(self.blue), self.alpha, self.size)
