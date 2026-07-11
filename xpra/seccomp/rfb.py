#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import os

from xpra.log import Logger
from xpra.seccomp import is_available
from xpra.seccomp.parse import PARSE_SYSCALLS
from xpra.util.env import envbool

log = Logger("seccomp")

ACTION_ENV = "XPRA_SECCOMP_RFB_ACTION"

# gate the RFB read filter independently of the draw / network-parse filters,
# so that enabling one does not silently enable the others:
ENABLED = envbool("XPRA_SECCOMP_RFB", envbool("XPRA_SECCOMP", False))

# the RFB client read thread reads from the socket and decodes framebuffer updates
# (raw / tight / zlib / cursor) inline, dispatching draw/challenge/clipboard packets:
# its syscall needs are the same as the main network parse thread.
RFB_SYSCALLS: tuple[str, ...] = PARSE_SYSCALLS


def is_enabled() -> bool:
    return ENABLED and is_available()


def install_thread() -> bool:
    if not is_enabled():
        return False
    from xpra.seccomp import _native
    action = get_action()
    log("installing rfb read thread seccomp policy with action=%s", action)
    _native.install_filter(RFB_SYSCALLS, action)
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
