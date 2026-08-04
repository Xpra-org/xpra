# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import platform_import


def get_auto_gsettings() -> dict[tuple[str, str], str]:
    """Return platform appearance preferences as serialized GVariant values."""
    return {}


platform_import(globals(), "gsettings", False, "get_auto_gsettings")
