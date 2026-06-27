# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: language_level=3

from libc.errno cimport EPERM
from libc.string cimport strerror
from libc.stdint cimport uint32_t
from cpython.bytes cimport PyBytes_AsString

cdef extern from "seccomp.h":
    ctypedef void* scmp_filter_ctx

    scmp_filter_ctx seccomp_init(uint32_t def_action)
    int seccomp_load(scmp_filter_ctx ctx)
    void seccomp_release(scmp_filter_ctx ctx)
    int seccomp_rule_add(scmp_filter_ctx ctx, uint32_t action, int syscall, unsigned int arg_cnt, ...)
    int seccomp_syscall_resolve_name(const char *name)

cdef extern from "sys/prctl.h":
    int prctl(int option, unsigned long arg2, unsigned long arg3, unsigned long arg4, unsigned long arg5)
    int PR_SET_NO_NEW_PRIVS


cdef inline uint32_t scmp_act_errno(unsigned int code):
    return 0x00050000 | (code & 0x0000FFFF)


cdef inline uint32_t action_value(str action):
    if action == "allow":
        return 0x7FFF0000
    if action == "log":
        return 0x7FFC0000
    if action == "errno":
        return scmp_act_errno(EPERM)
    if action == "kill_process":
        return 0x80000000
    return 0x00000000


cdef inline void raise_seccomp_error(str what, int code):
    cdef int err = -code if code < 0 else code
    if err <= 0:
        err = EPERM
    raise RuntimeError(f"{what} failed: {(<bytes>strerror(err)).decode('latin1')} ({err})")


def install_filter(syscalls, str action="kill_thread") -> None:
    cdef scmp_filter_ctx ctx = NULL
    cdef int r
    cdef int nr
    cdef bytes syscall_name
    if prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise_seccomp_error("prctl(PR_SET_NO_NEW_PRIVS)", EPERM)
    ctx = seccomp_init(action_value(action))
    if ctx == NULL:
        raise RuntimeError("seccomp_init failed")
    try:
        for name in syscalls:
            syscall_name = str(name).encode("ascii")
            nr = seccomp_syscall_resolve_name(PyBytes_AsString(syscall_name))
            if nr < 0:
                raise RuntimeError(f"unknown seccomp syscall {name!r}")
            r = seccomp_rule_add(ctx, 0x7FFF0000, nr, 0)
            if r != 0:
                raise_seccomp_error(f"seccomp_rule_add({name})", r)
        r = seccomp_load(ctx)
        if r != 0:
            raise_seccomp_error("seccomp_load", r)
    finally:
        if ctx != NULL:
            seccomp_release(ctx)
