#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: language_level=3

import os

from libc.errno cimport errno
from libc.stdint cimport uint64_t


cdef extern from *:
    """
    #include <stdint.h>
    #include <sys/prctl.h>
    #include <sys/syscall.h>
    #include <unistd.h>

    #ifndef LANDLOCK_CREATE_RULESET_VERSION
    #define LANDLOCK_CREATE_RULESET_VERSION (1U << 0)
    #endif
    #ifndef LANDLOCK_RULE_PATH_BENEATH
    #define LANDLOCK_RULE_PATH_BENEATH 1
    #endif
    #ifndef LANDLOCK_RESTRICT_SELF_TSYNC
    #define LANDLOCK_RESTRICT_SELF_TSYNC (1U << 3)
    #endif

    struct xpra_landlock_ruleset_attr {
        uint64_t handled_access_fs;
        uint64_t handled_access_net;
        uint64_t scoped;
    };

    struct xpra_landlock_path_beneath_attr {
        uint64_t allowed_access;
        int32_t parent_fd;
    } __attribute__((packed));

    static long xpra_landlock_get_abi(void) {
        return syscall(SYS_landlock_create_ruleset, NULL, 0,
                       LANDLOCK_CREATE_RULESET_VERSION);
    }

    static long xpra_landlock_create_ruleset(uint64_t handled_access_fs) {
        const struct xpra_landlock_ruleset_attr attr = {
            .handled_access_fs = handled_access_fs,
            .handled_access_net = 0,
            .scoped = 0,
        };
        return syscall(SYS_landlock_create_ruleset, &attr, sizeof(attr), 0);
    }

    static long xpra_landlock_add_path_rule(int ruleset_fd, int parent_fd,
                                             uint64_t allowed_access) {
        const struct xpra_landlock_path_beneath_attr attr = {
            .allowed_access = allowed_access,
            .parent_fd = parent_fd,
        };
        return syscall(SYS_landlock_add_rule, ruleset_fd,
                       LANDLOCK_RULE_PATH_BENEATH, &attr, 0);
    }

    static long xpra_landlock_restrict_self(int ruleset_fd, int sync_threads) {
        if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0)
            return -1;
        const unsigned int flags = sync_threads ? LANDLOCK_RESTRICT_SELF_TSYNC : 0;
        return syscall(SYS_landlock_restrict_self, ruleset_fd, flags);
    }
    """
    long xpra_landlock_get_abi()
    long xpra_landlock_create_ruleset(uint64_t handled_access_fs)
    long xpra_landlock_add_path_rule(int ruleset_fd, int parent_fd, uint64_t allowed_access)
    long xpra_landlock_restrict_self(int ruleset_fd, int sync_threads)


cdef inline long checked(long result, str operation) except? -2:
    if result < 0:
        error = errno
        raise OSError(error, f"{operation} failed: {os.strerror(error)}")
    return result


def get_abi_version() -> int:
    return checked(xpra_landlock_get_abi(), "landlock_create_ruleset(VERSION)")


def create_ruleset(unsigned long long handled_access_fs) -> int:
    return checked(xpra_landlock_create_ruleset(handled_access_fs), "landlock_create_ruleset")


def add_path_rule(int ruleset_fd, int parent_fd, unsigned long long allowed_access) -> None:
    checked(xpra_landlock_add_path_rule(ruleset_fd, parent_fd, allowed_access), "landlock_add_rule")


def restrict_self(int ruleset_fd, bint sync_threads=False) -> None:
    checked(xpra_landlock_restrict_self(ruleset_fd, sync_threads), "landlock_restrict_self")
