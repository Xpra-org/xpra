# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any


def get_pyobjc_version():
    try:
        import objc
        return objc.__version__
    except ImportError:
        return None


def get_version_info() -> dict[str, Any]:
    d = {}
    v = get_pyobjc_version()
    if v:
        d["pyobjc.version"] = v
    return d
