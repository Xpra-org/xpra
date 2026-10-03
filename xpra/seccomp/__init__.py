#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import sys

from xpra.util.env import envbool

LINUX = sys.platform.startswith("linux")
ENABLED = envbool("XPRA_SECCOMP", envbool("XPRA_SECCOMP_DECODE", False))


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


# faults raised by the thread itself: these cannot be redirected to another thread,
# and blocking them would turn a crash we can report (faulthandler) into a silent kill:
SYNCHRONOUS_SIGNALS: tuple[str, ...] = ("SIGSEGV", "SIGBUS", "SIGFPE", "SIGILL", "SIGTRAP", "SIGSYS", "SIGABRT")


def block_async_signals() -> None:
    # a process-directed signal (ie: `SIGCHLD` when a subprocess exits, `SIGINT`, ...)
    # is delivered to any thread that does not block it, and the C-level python handler
    # then runs on that thread: it writes to the signal wakeup fd, which a filter may not allow.
    # Python handlers only ever run on the main thread anyway, so block them all here -
    # the mask is inherited by any thread we spawn:
    import signal
    sync = {getattr(signal, name) for name in SYNCHRONOUS_SIGNALS if hasattr(signal, name)}
    signal.pthread_sigmask(signal.SIG_BLOCK, signal.valid_signals() - sync)


def install_filter(syscalls: tuple[str, ...], action: str, masked_rules=()) -> None:
    # every filter must be installed through this function, on the thread it applies to:
    from xpra.seccomp import _native
    from xpra.seccomp.glibc import prepare
    prepare()
    block_async_signals()
    _native.install_filter(syscalls, action, masked_rules)
