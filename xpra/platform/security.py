# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import platform_import


def harden_process() -> None:
    """Apply platform process hardening. Safe to call more than once."""


platform_import(globals(), "security", True, "harden_process")
