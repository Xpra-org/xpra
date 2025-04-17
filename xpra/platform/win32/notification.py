#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable


def get_backends() -> list[Callable]:
    from xpra.platform.win32.notifier import Win32_Notifier
    return [Win32_Notifier, ]
