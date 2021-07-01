# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2015-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# xxhash wrapper

#cython: auto_pickle=False, wraparound=False, cdivision=True, language_level=3

cdef extern from "xxhash.h":
    ctypedef unsigned long long XXH64_hash_t
    #XXH64_hash_t XXH64(const void* input, size_t length, unsigned long long seed) nogil
    XXH64_hash_t XXH3_64bits(const void* data, size_t len) nogil

#cdef unsigned long long xxh64(const void* input, size_t length, unsigned long long seed) nogil:
#    return XXH64(input, length, seed)

cdef unsigned long long xxh3(const void* input, size_t length) nogil:
    return XXH3_64bits(input, length)
