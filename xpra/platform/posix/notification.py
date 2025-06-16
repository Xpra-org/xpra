#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.log import Logger


def get_backends() -> list[Callable]:
    log = Logger("notify")
    ncs: list[Callable] = []
    try:
        from xpra.notification.dbus_backend import DBUS_Notifier_factory
        ncs.append(DBUS_Notifier_factory)
    except Exception as e:
        log("cannot load dbus notifier: %s", e)
    try:
        from xpra.notification.pynotify_backend import PyNotifyNotifier
        ncs.append(PyNotifyNotifier)
    except Exception as e:
        log("cannot load pynotify notifier: %s", e)
    return ncs
