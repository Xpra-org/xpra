# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "vpl_log.h":
    ctypedef void (*vpl_log_fn)(const char *msg)


cdef void vpl_log_callback(const char *msg) noexcept with gil
