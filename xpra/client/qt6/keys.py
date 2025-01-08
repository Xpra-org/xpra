# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from PyQt6.QtCore import Qt

key_names: dict[Qt.Key, str] = {}

for attr in dir(Qt.Key):
    if attr.startswith("Key_"):
        key_enum = getattr(Qt.Key, attr)
        key_names[key_enum] = attr[4:]
