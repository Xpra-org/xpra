# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util.env import shellsub
from xpra.os_util import get_group_id, POSIX
from xpra.util.stats import std_unit
from xpra.log import Logger

log = Logger("mmap")

MMAP_GROUP = os.environ.get("XPRA_MMAP_GROUP", "xpra")
DEFAULT_TOKEN_BYTES: int = 128

"""
Utility functions for communicating via mmap
"""


def get_socket_group(socket_filename) -> int:
    if isinstance(socket_filename, str) and os.path.exists(socket_filename):
        s = os.stat(socket_filename)
        return s.st_gid
    log.warn(f"Warning: missing valid socket filename {socket_filename!r} to set mmap group")
    return -1


def xpra_group() -> int:
    if POSIX:
        try:
            groups = os.getgroups()
            group_id = get_group_id(MMAP_GROUP)
            log("xpra_group() group(%s)=%s, groups=%s", MMAP_GROUP, group_id, groups)
            if group_id and group_id in groups:
                return group_id
        except Exception:
            log("xpra_group()", exc_info=True)
    return 0


def validate_size(size: int) -> None:
    if size < 64 * 1024 * 1024:
        raise ValueError("mmap size is too small: %sB (minimum is 64MB)" % std_unit(size))
    if size > 16 * 1024 * 1024 * 1024:
        raise ValueError("mmap is too big: %sB (maximum is 4GB)" % std_unit(size))


def get_mmap_dir() -> str:
    from xpra.platform.paths import get_mmap_dir as get_platform_mmap_dir
    mmap_dir = get_platform_mmap_dir()
    subs = os.environ.copy()
    subs |= {
        "UID": str(os.getuid()),
        "GID": str(os.getgid()),
        "PID": str(os.getpid()),
    }
    mmap_dir = shellsub(mmap_dir, subs)
    if mmap_dir and not os.path.exists(mmap_dir):
        os.mkdir(mmap_dir, 0o700)
    if not mmap_dir or not os.path.exists(mmap_dir):
        raise RuntimeError("mmap directory %s does not exist!" % mmap_dir)
    return mmap_dir
