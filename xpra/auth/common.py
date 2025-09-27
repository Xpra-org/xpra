#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import TypeAlias

from xpra.util.env import get_saved_env
from xpra.auth.sys_auth_base import log, DEFAULT_UID, DEFAULT_GID
from xpra.os_util import POSIX

SessionData: TypeAlias = tuple[int, int, list[str], dict[str, str], dict[str, str]]


def parse_uid(v) -> int:
    if v:
        try:
            return int(v)
        except (TypeError, ValueError):
            log(f"uid {v!r} is not an integer")
    if POSIX:
        try:
            import pwd  # pylint: disable=import-outside-toplevel
            return pwd.getpwnam(v or DEFAULT_UID).pw_uid
        except Exception as e:
            log(f"parse_uid({v})", exc_info=True)
            log.error(f"Error: cannot find uid of {v!r}: {e}")
        return os.getuid()
    return -1


def parse_gid(v) -> int:
    if v:
        try:
            return int(v)
        except (TypeError, ValueError):
            log(f"gid {v!r} is not an integer")
    if POSIX:
        try:
            import grp  # pylint: disable=import-outside-toplevel
            return grp.getgrnam(v or DEFAULT_GID).gr_gid
        except Exception as e:
            log(f"parse_gid({v})", exc_info=True)
            log.error(f"Error: cannot find gid of {v!r}: {e}")
        return os.getgid()
    return -1


def get_exec_env(display="auto") -> dict[str, str]:
    env = os.environ.copy()
    # remove usless vars:
    for k in ("LS_COLORS", ""):
        env.pop(k, "")
    if display == "auto":
        # if the server was started from an existing display,
        # show the OTP there
        saved_env = get_saved_env()
        for key in ("DISPLAY", "WAYLAND_DISPLAY"):
            if key in saved_env:
                env[key] = saved_env[key]
    elif display:
        env["DISPLAY"] = display
    return env
