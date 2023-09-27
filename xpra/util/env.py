# This file is part of Xpra.
# Copyright (C) 2019-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os


def unsetenv(*varnames) -> None:
    for x in varnames:
        os.environ.pop(x, None)


def hasenv(name : str) -> bool:
    return os.environ.get(name) is not None


def envint(name : str, d:int=0) -> int:
    try:
        return int(os.environ.get(name, d))
    except ValueError:
        return d


def envbool(name : str, d:bool=False) -> bool:
    try:
        v = os.environ.get(name, "").lower()
        if v is None:
            return d
        if v in ("yes", "true", "on"):
            return True
        if v in ("no", "false", "off"):
            return False
        return bool(int(v))
    except ValueError:
        return d


def envfloat(name : str, d:float=0) -> float:
    try:
        return float(os.environ.get(name, d))
    except ValueError:
        return d
