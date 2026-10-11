#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes
import os
import resource

from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("util")

DENY_ATTACH = envbool("XPRA_DENY_ATTACH", True)

PT_DENY_ATTACH = 31

CTL_KERN = 1
KERN_PROC = 14
KERN_PROC_PID = 1
# offset of `kp_proc.p_flag` in `struct kinfo_proc`, see <sys/sysctl.h> and <sys/proc.h>:
P_FLAG_OFFSET = 32
P_TRACED = 0x800
KINFO_PROC_SIZE = 648


def _get_libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.ptrace.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
    libc.ptrace.restype = ctypes.c_int
    libc.sysctl.argtypes = (ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
                            ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                            ctypes.c_void_p, ctypes.c_size_t)
    libc.sysctl.restype = ctypes.c_int
    return libc


def _raise_oserror(operation: str) -> None:
    errno = ctypes.get_errno()
    raise OSError(errno, f"{operation} failed: {os.strerror(errno)}")


def is_traced(libc=None) -> bool:
    libc = libc or _get_libc()
    mib = (ctypes.c_int * 4)(CTL_KERN, KERN_PROC, KERN_PROC_PID, os.getpid())
    info = ctypes.create_string_buffer(KINFO_PROC_SIZE)
    size = ctypes.c_size_t(KINFO_PROC_SIZE)
    if libc.sysctl(mib, 4, info, ctypes.byref(size), None, 0) != 0:
        _raise_oserror("sysctl(KERN_PROC_PID)")
    if size.value < P_FLAG_OFFSET + 4:
        raise OSError(f"sysctl(KERN_PROC_PID) returned only {size.value} bytes")
    p_flag = ctypes.c_int.from_buffer(info, P_FLAG_OFFSET).value
    return bool(p_flag & P_TRACED)


def deny_attach(libc=None) -> bool:
    """
    Prevent debuggers and dtrace from attaching to this process.
    A process that is already being traced exits when it calls PT_DENY_ATTACH,
    so we skip it in that case.
    """
    libc = libc or _get_libc()
    if is_traced(libc):
        log("process is being traced, not calling PT_DENY_ATTACH")
        return False
    if libc.ptrace(PT_DENY_ATTACH, 0, None, 0) != 0:
        _raise_oserror("ptrace(PT_DENY_ATTACH)")
    return True


def disable_core_dumps() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def harden_process() -> None:
    """Protect server credentials and encryption keys held in process memory."""
    disable_core_dumps()
    if DENY_ATTACH:
        deny_attach()
