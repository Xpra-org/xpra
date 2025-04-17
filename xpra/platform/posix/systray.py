# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.env import first_time, get_saved_env_var


def get_forwarding_backends() -> list[type]:
    return _try_load_appindicator()


def get_backends() -> list[type]:
    return _try_load_appindicator()


def _try_load_appindicator() -> list[type]:
    try:
        from xpra.platform.posix.appindicator_tray import AppindicatorTray
        return [AppindicatorTray]
    except (ImportError, ValueError):
        if first_time("no-appindicator"):
            from xpra.log import Logger
            log = Logger("posix", "tray")
            log("cannot load appindicator tray", exc_info=True)
            log.warn("Warning: appindicator library not found")
            log.warn(" you may want to install libappindicator")
            log.warn(" to enable the system tray.")
            if get_saved_env_var("XDG_CURRENT_DESKTOP", "").upper().find("GNOME") >= 0:
                log.warn(" With gnome-shell, you may also need some extensions:")
                log.warn(" 'top icons plus' and / or 'appindicator'")
    return []
