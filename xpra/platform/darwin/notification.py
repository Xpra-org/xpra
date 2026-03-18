#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable, Sequence


def get_backends() -> Sequence[Callable]:
    from Foundation import NSUserNotificationCenter
    if NSUserNotificationCenter.defaultUserNotificationCenter():
        from xpra.platform.darwin.notifier import OSX_Notifier
        return (OSX_Notifier, )
    return ()
