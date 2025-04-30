#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import platform_import


def get_menu_helper_class() -> type | None:
    # classes that generate menus for xpra's system tray
    # let the toolkit classes use their own
    return None


def get_backends(*_args) -> list[type]:
    # the classes we can use for our system tray:
    # let the toolkit classes use their own
    return []


def get_forwarding_backends(*_args) -> list[type]:
    # the classes we can use for application system tray forwarding:
    # let the toolkit classes use their own
    return []


platform_import(globals(), "systray", False,
                "get_menu_helper_class",
                "get_backends",
                "get_forwarding_backends",
                )
