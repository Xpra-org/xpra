# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, cdivision=True

from libc.time cimport time_t

from xpra.log import Logger
log = Logger("util")


cdef extern from "monotonic_ctime.h":
    double get_monotonic_time()

def _monotonic_time():
    return get_monotonic_time()

cdef inline double monotonic_time():
    return get_monotonic_time()
