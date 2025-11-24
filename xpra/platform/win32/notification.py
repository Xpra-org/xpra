#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable


def get_backends() -> list[Callable]:
    try:
        from xpra.platform.win32.notifier import Win32_Notifier
        return [Win32_Notifier, ]
    except ImportError as e:
        from xpra.log import Logger
        log = Logger("win32")
        log("get_backends()", exc_info=True)
        log.error("Error: failed to load Win32 Notifier")
        log.estr(e)
        return []
