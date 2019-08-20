# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, cdivision=True, language_level=3
from __future__ import absolute_import

from libc.time cimport time_t  #pylint: disable=syntax-error


cdef extern from "monotonic_ctime.h":
    double get_monotonic_time()

def _monotonic_time():
    return get_monotonic_time()

cdef inline double monotonic_time():
    return get_monotonic_time()
