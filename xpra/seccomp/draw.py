#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import os

from xpra.log import Logger
from xpra.seccomp import is_enabled

log = Logger("seccomp")

ACTION_ENV = "XPRA_SECCOMP_DRAW_ACTION"

# permissive baseline shared with the network parse and rfb filters.
# those threads dispatch many packet handlers (hello, audio, encodings, ...)
# with a large lazy-import surface, so they keep the ability to open files -
# see `xpra/seccomp/parse.py` and `xpra/seccomp/rfb.py`:
BASE_SYSCALLS: tuple[str, ...] = (
    "access",
    "arch_prctl",
    "brk",
    "clock_gettime",
    "clone",
    "clone3",
    "close",
    "dup",
    "dup2",
    "dup3",
    "epoll_create1",
    "epoll_ctl",
    "epoll_pwait",
    "epoll_wait",
    "exit",
    "exit_group",
    "fadvise64",
    "fallocate",
    "fcntl",
    "fstat",
    "fsync",
    "ftruncate",
    "futex",
    "getcwd",
    "getdents64",
    "getegid",
    "geteuid",
    "getgid",
    "getpid",
    "getppid",
    "getrandom",
    "gettid",
    "getuid",
    "ioctl",
    "lseek",
    "madvise",
    "membarrier",
    "mincore",
    "mkdir",
    "mmap",
    "mprotect",
    "mremap",
    "munmap",
    "nanosleep",
    "newfstatat",
    "open",
    "openat",
    "poll",
    "ppoll",
    "pread64",
    "prctl",
    "prlimit64",
    "pselect6",
    "read",
    "readlink",
    "readlinkat",
    "recvmsg",
    "rename",
    "renameat",
    "renameat2",
    "rseq",
    "rt_sigaction",
    "rt_sigprocmask",
    "sched_getaffinity",
    "sched_yield",
    "select",
    "sendmsg",
    "set_robust_list",
    "set_tid_address",
    "sigaltstack",
    "stat",
    "statx",
    "tgkill",
    "unlink",
    "unlinkat",
    "write",
    "writev",
    "clock_nanosleep",
    "restart_syscall",
)

# the draw thread only decodes images that are already in memory: the decoders
# it uses are pre-loaded and pre-warmed by the codec selftest (XPRA_CODEC_SELFTEST,
# on by default) before this thread starts, and hardware decoders are disabled
# under seccomp (see `xpra/client/subsystem/encoding.py`). So it never needs to
# open, create or delete files - blocking those confines a decoder bug from
# touching the filesystem. (Debug image dumping via XPRA_SAVE_TO_FILE is turned
# off under seccomp, see `xpra/codecs/debug.py`.)
FILE_SYSCALLS: tuple[str, ...] = (
    "open",
    "openat",
    "unlink",
    "unlinkat",
    "mkdir",
    "rename",
    "renameat",
    "renameat2",
    "ftruncate",
    "fallocate",
)

DRAW_SYSCALLS: tuple[str, ...] = tuple(s for s in BASE_SYSCALLS if s not in FILE_SYSCALLS)


def install_thread() -> bool:
    if not is_enabled():
        return False
    from xpra.seccomp import _native
    action = get_action()
    log("installing draw thread seccomp policy with action=%s", action)
    _native.install_filter(DRAW_SYSCALLS, action)
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
