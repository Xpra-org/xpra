#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import sys

from xpra.util.env import envbool

LINUX = sys.platform.startswith("linux")
ENABLED = envbool("XPRA_SECCOMP", envbool("XPRA_SECCOMP_DRAW", False))


def is_available() -> bool:
    if not LINUX:
        return False
    try:
        from xpra.seccomp import _native
        return bool(_native)
    except ImportError:
        return False


def is_enabled() -> bool:
    return LINUX and ENABLED and is_available()
