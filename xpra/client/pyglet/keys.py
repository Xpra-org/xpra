#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from pyglet.window import key


keynames = {}
for attr in dir(key):
    if attr.startswith("_") or not attr.isupper():
        continue
    value = getattr(key, attr)
    keynames[value] = attr
