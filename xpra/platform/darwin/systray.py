#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.platform.darwin import get_OSXApplication


def get_menu_helper_class() -> Callable | None:
    if get_OSXApplication():
        from xpra.platform.darwin.menu import getOSXMenuHelper
        return getOSXMenuHelper
    return None


def get_backends() -> list[type]:
    if get_OSXApplication():
        from xpra.platform.darwin.tray import OSXTray
        return [OSXTray]
    return []
