# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger

log = Logger("util", "exec")

DEF PROC_FILLSTATUS = 0x0020    #read status
DEF PROC_PID = 0x1000           #process id numbers ( 0   terminated )


cdef extern from "libproc2/pids.h":
    ctypedef enum pids_item:
        PIDS_ID_PPID

    # Opaque handle used by procps to store its buffers
    struct pids_info:
        pass

    # Reports counts of queried processes (both total, and per-state which we don't use)
    struct pids_counts:
        int total

    # Variant type containing a value for each query flag
    union pids_result_variant:
        int s_int

    struct pids_result:
        int item
        pids_result_variant result

    struct pids_stack:
        pids_result *head

    # Return buffer that reports queried process counts and actual results
    struct pids_fetch:
        pids_counts *counts
        pids_stack **stacks

    ctypedef enum pids_select_type:
        PIDS_SELECT_PID
        PIDS_SELECT_PID_THREADS
        PIDS_SELECT_UID
        PIDS_SELECT_UID_THREADS

    int procps_pids_new(pids_info **info, pids_item *items, int numitems)
    int procps_pids_unref(pids_info **info)
    pids_fetch *procps_pids_select(pids_info *info, unsigned*pids, int pidcount, int select_type)

def get_parent_pid(unsigned int pid) -> long:
    cdef pids_info *handle = NULL
    cdef pids_item selector = PIDS_ID_PPID
    if procps_pids_new(&handle, &selector, 1) != 0:
        return 0

    cdef pids_fetch *query = procps_pids_select(handle, &pid, 1, PIDS_SELECT_PID)
    cdef int retval = 0
    if query != NULL and query.counts.total == 1 and query.stacks[0].head.item == PIDS_ID_PPID:
        retval = query.stacks[0].head.result.s_int

    procps_pids_unref(&handle)
    return retval
