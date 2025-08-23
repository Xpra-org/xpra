# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cython
from libc.string cimport memset

from xpra.log import Logger

log = Logger("util", "exec")

DEF PROC_FILLSTATUS = 0x0020    #read status
DEF PROC_PID = 0x1000           #process id numbers ( 0   terminated )


cdef extern from "proc/readproc.h":
    ctypedef int pid_t
    ctypedef struct proc_t:
        int ppid
        int pgrp        #process group id
        int session     #session id
        int nlwp        #stat,status     number of threads, or 0 if no clue
        int tgid        #(special)       thread group ID, the POSIX PID (see also: tid)
        int tty         #stat            full device number of controlling terminal

    proc_t * get_proc_stats(pid_t pid, proc_t *p)

    ctypedef struct PROCTAB:
        pass

    PROCTAB* openproc(int flags, pid_t *pid)
    proc_t* readproc(PROCTAB *PT, proc_t *p)
    void closeproc(PROCTAB* PT)


def get_parent_pid(int pid) -> cython.ulong:
    cdef proc_t proc_info
    memset(&proc_info, 0, sizeof(proc_t))
    cdef PROCTAB *pt_ptr = openproc(PROC_FILLSTATUS | PROC_PID, &pid)
    try:
        if readproc(pt_ptr, &proc_info) and proc_info.ppid > 0:
            return proc_info.ppid
    finally:
        closeproc(pt_ptr);
    return 0
