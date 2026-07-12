#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import os

from xpra.log import Logger
from xpra.seccomp import is_available
from xpra.seccomp.draw import BASE_SYSCALLS
from xpra.util.env import envbool

log = Logger("seccomp")

ACTION_ENV = "XPRA_SECCOMP_MENU_ACTION"
ENABLED = envbool("XPRA_SECCOMP_MENU", envbool("XPRA_SECCOMP", False))

# Loading XDG menus requires directory traversal and reading XML, desktop files
# and icons. Keep the baseline's read-side filesystem calls, but drop
# operations which mutate the namespace or file contents, create descendants,
# or communicate over sockets. `open` and `openat` are added back below with
# flag constraints.
BLOCKED_SYSCALLS: tuple[str, ...] = (
    "clone",
    "clone3",
    "fallocate",
    "fsync",
    "ftruncate",
    "mkdir",
    "open",
    "openat",
    "recvmsg",
    "rename",
    "renameat",
    "renameat2",
    "sendmsg",
    "unlink",
    "unlinkat",
    "write",
    "writev",
)

MENU_SYSCALLS: tuple[str, ...] = tuple(
    s for s in BASE_SYSCALLS if s not in BLOCKED_SYSCALLS
)

# Mask every flag which can make an open writable or create/replace file data.
# Other read-side flags such as O_CLOEXEC, O_DIRECTORY and O_NOFOLLOW remain
# valid.
# O_TMPFILE also contains O_DIRECTORY, which is valid for read-only opens.
# Mask only its otherwise unique bit so normal directory traversal survives.
TMPFILE_WRITE_FLAG = getattr(os, "O_TMPFILE", 0) & ~os.O_DIRECTORY
WRITE_OPEN_FLAGS = os.O_ACCMODE
WRITE_OPEN_FLAGS |= os.O_CREAT
WRITE_OPEN_FLAGS |= os.O_TRUNC
WRITE_OPEN_FLAGS |= os.O_APPEND
WRITE_OPEN_FLAGS |= TMPFILE_WRITE_FLAG
MENU_MASKED_RULES: tuple[tuple[str, int, int, int], ...] = (
    ("open", 1, WRITE_OPEN_FLAGS, 0),
    ("openat", 2, WRITE_OPEN_FLAGS, 0),
    # Preserve normal logging without granting writes to arbitrary descriptors
    # shared with the rest of the process.
    ("write", 0, (1 << 64) - 1, 1),
    ("write", 0, (1 << 64) - 1, 2),
    ("writev", 0, (1 << 64) - 1, 1),
    ("writev", 0, (1 << 64) - 1, 2),
)


def is_enabled() -> bool:
    return ENABLED and is_available()


def install_thread() -> bool:
    if not is_enabled():
        return False
    from xpra.seccomp import _native
    action = get_action()
    log("installing menu loading thread seccomp policy with action=%s", action)
    _native.install_filter(MENU_SYSCALLS, action, MENU_MASKED_RULES)
    return True


def get_action() -> str:
    action = str(os.environ.get(ACTION_ENV, "kill_process")).strip().lower()
    if action in ("kill", "kill-thread", "kill_thread"):
        return "kill_thread"
    if action in ("kill_process", "kill-process"):
        return "kill_process"
    if action in ("errno", "log", "allow"):
        return action
    log.warn("Warning: invalid %s value %r", ACTION_ENV, action)
    return "kill_process"
