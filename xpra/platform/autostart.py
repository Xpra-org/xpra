# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import platform_import


def set_autostart(_enabled: bool) -> None:
    """
    win32 and posix platforms will override this function
    """


def get_status() -> str:
    return ""


platform_import(globals(), "autostart", False,
                "set_autostart", "get_status")
