# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile

from xpra.util.env import shellsub, osexpand
from xpra.os_util import get_group_id, POSIX
from xpra.util.stats import std_unit
from xpra.log import Logger

log = Logger("mmap")

MMAP_GROUP = os.environ.get("XPRA_MMAP_GROUP", "xpra")
DEFAULT_TOKEN_BYTES: int = 128
# the token size is chosen by the peer, so it needs an upper bound:
# (leave some room for peers using a larger token than we do)
MAX_TOKEN_BYTES: int = DEFAULT_TOKEN_BYTES * 4

"""
Utility functions for communicating via mmap
"""


def split_paths(value: str) -> tuple[str, ...]:
    """
        Splits the list of paths specified using the `mmap` option.
        The path separator for the platform is used: ";" on MS Windows and ":" everywhere else,
        a comma is also accepted when the platform's separator is not found.
        (never split on ":" on MS Windows: that would break "C:\\..." paths)
    """
    if not value.strip():
        return ()
    sep = os.path.pathsep if os.path.pathsep in value else ","
    return tuple(x.strip() for x in value.split(sep) if x.strip())


def get_socket_group(socket_filename: str) -> int:
    if socket_filename and os.path.exists(socket_filename):
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


class MmapPointerError(ValueError):
    """
    The peer has stored an invalid pointer in the shared control header.
    This should never happen with a well behaved peer,
    so the connection should be terminated.
    """


MIN_SIZE = 64 * 1024 * 1024
# the `data_start` and `data_end` pointers stored in the control header are 32-bit
# and hold absolute offsets in the range [8, size], so `size` itself must be
# representable: anything from 4GB up would truncate to zero, which `read_pointer`
# would then mistake for an unused area.
# (the 8 byte header only costs us payload space, not address space)
MAX_SIZE = 4 * 1024 * 1024 * 1024


def validate_size(size: int) -> None:
    if size < MIN_SIZE:
        raise ValueError("mmap size is too small: %sB (minimum is 64MB)" % std_unit(size))
    if size >= MAX_SIZE:
        raise ValueError("mmap is too big: %sB (must be smaller than 4GB)" % std_unit(size))


def get_user_mmap_dir(uid: int) -> str:
    """
        The mmap directory of a given user, ie: `/run/user/1000/xpra`.
        For any user but ourselves this is only a guess:
        we cannot know how that user's session is configured,
        so this directory may not exist - and it is never created here.
    """
    from xpra.platform.posix.paths import get_runtime_dir
    runtime_dir = get_runtime_dir()
    if "$UID" not in runtime_dir and uid != os.getuid():
        # a non-standard runtime directory: it is ours,
        # which tells us nothing about any other user
        log(f"cannot use runtime directory {runtime_dir!r} for uid {uid}")
        return ""
    xrd = osexpand(runtime_dir, uid=uid)
    if not os.path.isabs(xrd):
        log(f"unusable runtime directory {xrd!r} for uid {uid}")
        return ""
    return os.path.join(xrd, "xpra")


def get_default_mmap_dirs(peer_uid: int = -1) -> tuple[str, ...]:
    """
        The directories where a client's mmap file is allowed to be found
        when no directory has been specified using the `mmap` option:
        our own mmap directory and, if the peer belongs to another user,
        the standard mmap directory for that user.
        The system temporary directory is never allowed implicitly:
        every user can create files there.
    """
    dirs = []
    try:
        mmap_dir = get_mmap_dir()
    except (OSError, RuntimeError) as e:
        log(f"get_default_mmap_dirs: no mmap directory: {e}")
        mmap_dir = ""
    if mmap_dir:
        if mmap_dir != tempfile.gettempdir():
            dirs.append(mmap_dir)
        else:
            # `do_get_mmap_dir` falls back to the temporary directory
            # when there is no runtime directory - that is not a location we can trust,
            # the `mmap` option must be used to allow it explicitly:
            log(f"not using the system temporary directory {mmap_dir!r} as mmap directory")
    if POSIX and peer_uid >= 0:
        peer_dir = get_user_mmap_dir(peer_uid)
        if peer_dir and peer_dir not in dirs:
            dirs.append(peer_dir)
    log("get_default_mmap_dirs(%i)=%s", peer_uid, dirs)
    return tuple(dirs)


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
