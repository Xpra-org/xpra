# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, cdivision=True

from libc.time cimport time_t

from xpra.log import Logger
log = Logger("util")


cdef extern from "sys/time.h":
    cdef struct timespec:
        time_t   tv_sec         #seconds
        long     tv_nsec        #nanoseconds

cdef extern from "monotonic_ctime.h":
    void get_monotonic_time(timespec *ts)


def monotonic_time():
    cdef timespec ts
    get_monotonic_time(&ts)
    return ts.tv_sec + ts.tv_nsec/1000000000.0
