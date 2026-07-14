#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import errno
import os
import sys
from collections.abc import Iterable
from enum import IntFlag

from xpra.log import Logger

log = Logger("landlock")


class FSAccess(IntFlag):
    EXECUTE = 1 << 0
    WRITE_FILE = 1 << 1
    READ_FILE = 1 << 2
    READ_DIR = 1 << 3
    REMOVE_DIR = 1 << 4
    REMOVE_FILE = 1 << 5
    MAKE_CHAR = 1 << 6
    MAKE_DIR = 1 << 7
    MAKE_REG = 1 << 8
    MAKE_SOCK = 1 << 9
    MAKE_FIFO = 1 << 10
    MAKE_BLOCK = 1 << 11
    MAKE_SYM = 1 << 12
    REFER = 1 << 13
    TRUNCATE = 1 << 14
    IOCTL_DEV = 1 << 15
    RESOLVE_UNIX = 1 << 16


ALL_FS_ACCESS = FSAccess((1 << 17) - 1)
READ_ACCESS = FSAccess.EXECUTE | FSAccess.READ_FILE | FSAccess.READ_DIR | FSAccess.IOCTL_DEV | FSAccess.RESOLVE_UNIX
DEVICE_ACCESS = FSAccess.READ_FILE | FSAccess.READ_DIR | FSAccess.WRITE_FILE | FSAccess.IOCTL_DEV
WRITE_ACCESS = FSAccess.WRITE_FILE | FSAccess.REMOVE_DIR | FSAccess.REMOVE_FILE | FSAccess.MAKE_DIR | FSAccess.MAKE_REG | FSAccess.MAKE_FIFO | FSAccess.MAKE_SYM | FSAccess.REFER | FSAccess.TRUNCATE


def access_for_abi(abi: int) -> FSAccess:
    """Return the filesystem rights understood by a Landlock ABI version."""
    if abi < 1:
        return FSAccess(0)
    access = FSAccess((1 << 13) - 1)
    if abi >= 2:
        access |= FSAccess.REFER
    if abi >= 3:
        access |= FSAccess.TRUNCATE
    if abi >= 5:
        access |= FSAccess.IOCTL_DEV
    if abi >= 9:
        access |= FSAccess.RESOLVE_UNIX
    return access


def _get_native():
    from xpra.platform.posix import _landlock  # pylint: disable=import-outside-toplevel
    return _landlock


def get_abi_version() -> int:
    return int(_get_native().get_abi_version())


def is_available() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        return get_abi_version() > 0
    except (ImportError, OSError):
        return False


def canonical_paths(paths: Iterable[str]) -> tuple[str, ...]:
    canonical: list[str] = []
    for path in paths:
        if not path:
            continue
        expanded = os.path.expandvars(os.path.expanduser(path))
        real_path = os.path.realpath(os.path.abspath(expanded))
        if real_path not in canonical:
            canonical.append(real_path)
    return tuple(canonical)


def restrict_paths(read_paths: Iterable[str] = (), write_paths: Iterable[str] = (), *,
                   device_paths: Iterable[str] = (),
                   allow_socket_creation: bool = True, sync_threads: bool = False) -> int:
    """
    Restrict the calling thread, and optionally all process threads, to path rules.

    Paths in ``write_paths`` also receive read access. Missing paths are ignored:
    Landlock can only attach rules to existing filesystem objects.

    ``device_paths`` may be opened for reading and writing and used with ioctl,
    but filesystem entries cannot be created, removed or renamed beneath them.
    """
    native = _get_native()
    abi = int(native.get_abi_version())
    if sync_threads and abi < 9:
        raise OSError(errno.EOPNOTSUPP, f"Landlock ABI 9 is required for thread synchronization (found ABI {abi})")
    supported = access_for_abi(abi)
    if not supported:
        raise OSError(errno.EOPNOTSUPP, f"unsupported Landlock ABI {abi}")

    ro_access = READ_ACCESS & supported
    rw_access = (READ_ACCESS | WRITE_ACCESS) & supported
    if allow_socket_creation:
        rw_access |= FSAccess.MAKE_SOCK & supported

    rules: dict[str, FSAccess] = {}
    for path in canonical_paths(read_paths):
        rules[path] = rules.get(path, FSAccess(0)) | ro_access
    for path in canonical_paths(write_paths):
        rules[path] = rules.get(path, FSAccess(0)) | rw_access
    for path in canonical_paths(device_paths):
        rules[path] = rules.get(path, FSAccess(0)) | (DEVICE_ACCESS & supported)

    ruleset_fd = native.create_ruleset(int(ALL_FS_ACCESS & supported))
    try:
        for path, access in rules.items():
            if not os.path.exists(path):
                log("Landlock path does not exist: %r", path)
                continue
            if not os.path.isdir(path):
                log("Landlock path is not a directory: %r", path)
                continue
            path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                native.add_path_rule(ruleset_fd, path_fd, int(access))
            finally:
                os.close(path_fd)
        native.restrict_self(ruleset_fd, sync_threads)
    finally:
        os.close(ruleset_fd)
    log.info("Landlock ABI %i filesystem restrictions enabled", abi)
    return abi
