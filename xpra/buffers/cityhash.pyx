# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cityhash wrapper

#cython: boundscheck=False, wraparound=False

from libc.stdint cimport uint64_t, uint8_t

cdef extern from "city.h":
    uint64_t CityHash64(const char *buf, size_t len) nogil

cdef uint64_t cityhash64(uint8_t *data, size_t length) noexcept nogil:
    return CityHash64(<const char*> data, length)
