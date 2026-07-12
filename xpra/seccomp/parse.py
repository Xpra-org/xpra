#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import os

from xpra.log import Logger
from xpra.seccomp import is_available
from xpra.seccomp.draw import DRAW_SYSCALLS
from xpra.util.env import envbool

log = Logger("seccomp")

ACTION_ENV = "XPRA_SECCOMP_PARSE_ACTION"

# gate the network parse filter independently of the draw filter,
# so that `XPRA_SECCOMP_DRAW=1` does not silently enable it:
ENABLED = envbool("XPRA_SECCOMP_PARSE", envbool("XPRA_SECCOMP", False))

# syscalls the socket-reading threads need on top of the draw baseline:
# * `recvfrom` - what `socket.recv_into` maps to on x86_64
# * `getsockname` / `getsockopt` - read-only socket introspection used when
#   gathering connection info (peer credentials, unix socket path, ...)
# * `sysinfo` - read-only system statistics, used by `os.getloadavg()` in the
#   server-side ping handler (which stays on the parse thread):
SOCKET_SYSCALLS: tuple[str, ...] = (
    "recvfrom",
    "getsockname",
    "getsockopt",
    "sysinfo",
)

# the parse thread reads from the socket, decrypts, decompresses and decodes packets,
# and dispatches the packet handlers inline. Every handler that spawned a subprocess or
# did file I/O has been moved off this thread (file transfers, printing, `open-url`,
# `start-command`, control - see `docs/Usage/Seccomp.md`), so the parse filter now drops
# file access too, just like the draw filter: the draw baseline plus the socket syscalls.
# Caveat: a handler that lazily imports a module for the first time on this thread would
# still hit `openat`. The default action is `errno` (non-fatal) for exactly this reason -
# validate a deployment with `XPRA_SECCOMP_PARSE_ACTION=log` before switching to `strict`.
PARSE_SYSCALLS: tuple[str, ...] = DRAW_SYSCALLS + SOCKET_SYSCALLS


def is_enabled() -> bool:
    return ENABLED and is_available()


def install_thread() -> bool:
    if not is_enabled():
        return False
    from xpra.seccomp import _native
    action = get_action()
    log("installing parse thread seccomp policy with action=%s", action)
    _native.install_filter(PARSE_SYSCALLS, action)
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
