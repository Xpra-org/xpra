# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2015-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# xxhash wrapper

#cython: wraparound=False
from libc.stdint cimport uint64_t

cdef extern from "xxhash.h":
    ctypedef uint64_t XXH64_hash_t
    XXH64_hash_t XXH3_64bits(const void* data, size_t len) nogil

cdef uint64_t xxh3(const void* input, size_t length) noexcept nogil:
    return XXH3_64bits(input, length)
