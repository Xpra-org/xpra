#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import ctypes
import mmap
import os
import resource
from collections.abc import Iterator

from xpra.log import Logger

log = Logger("server")

PR_SET_DUMPABLE = 4


def _get_libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = (
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    )
    libc.prctl.restype = ctypes.c_int
    libc.madvise.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.madvise.restype = ctypes.c_int
    return libc


def _raise_oserror(operation: str) -> None:
    errno = ctypes.get_errno()
    raise OSError(errno, f"{operation} failed: {os.strerror(errno)}")


def disable_ptrace(libc=None) -> None:
    """Prevent unprivileged processes from inspecting this process."""
    libc = libc or _get_libc()
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        _raise_oserror("prctl(PR_SET_DUMPABLE)")


def disable_core_dumps() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def writable_private_mappings(maps_path: str = "/proc/self/maps") -> Iterator[tuple[int, int]]:
    """Yield writable private mappings which may contain process secrets."""
    with open(maps_path, encoding="latin1") as maps:
        for line in maps:
            fields = line.split(None, 2)
            if len(fields) < 2:
                continue
            address, permissions = fields[:2]
            if len(permissions) < 4 or permissions[1] != "w" or permissions[3] != "p":
                continue
            try:
                start_text, end_text = address.split("-", 1)
                start = int(start_text, 16)
                end = int(end_text, 16)
            except ValueError:
                continue
            if end > start:
                yield start, end


def mark_memory_nondumpable(libc=None, maps_path: str = "/proc/self/maps") -> tuple[int, int]:
    """Apply MADV_DONTDUMP to the process's writable private mappings."""
    dontdump = getattr(mmap, "MADV_DONTDUMP", 0)
    if not dontdump:
        return 0, 0
    libc = libc or _get_libc()
    marked = failed = 0
    for start, end in writable_private_mappings(maps_path):
        if libc.madvise(start, end - start, dontdump) == 0:
            marked += 1
        else:
            failed += 1
    return marked, failed


def harden_process() -> None:
    """Protect server credentials and encryption keys held in process memory."""
    disable_ptrace()
    disable_core_dumps()
    try:
        marked, failed = mark_memory_nondumpable()
    except OSError as e:
        log.warn("Warning: unable to exclude process memory from core dumps:")
        log.warn(" %s", e)
    else:
        log("marked %i writable private memory mappings MADV_DONTDUMP", marked)
        if failed:
            log.warn("Warning: failed to mark %i memory mappings MADV_DONTDUMP", failed)
