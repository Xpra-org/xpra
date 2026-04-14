#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable, Sequence


def get_backends() -> Sequence[Callable]:
    from xpra.log import Logger
    log = Logger("notify")

    def nomod(mod:str, e) -> None:
        log("unable to load %s: %s", mod, e)

    from xpra.platform.darwin import is_app_bundle
    if is_app_bundle():
        # Prefer the modern UNUserNotificationCenter (macOS 10.14+)
        try:
            from UserNotifications import UNUserNotificationCenter
            if UNUserNotificationCenter.currentNotificationCenter():
                from xpra.platform.darwin.notifier_un import UN_Notifier
                return (UN_Notifier, )
            else:
                nomod("UNUserNotification", "no current notification center")
        except (ImportError, Exception) as e:
            nomod("UNUserNotification", e)
    else:
        nomod("UNUserNotification", "not an app bundle")
    # Fall back to the deprecated NSUserNotificationCenter
    try:
        from Foundation import NSUserNotificationCenter
        if NSUserNotificationCenter.defaultUserNotificationCenter():
            from xpra.platform.darwin.notifier import OSX_Notifier
            return (OSX_Notifier, )
        else:
            nomod("OSX_Notifier", "no default user notification center")
    except (ImportError, Exception) as e:
        nomod("NSUserNotification", e)
    return ()
