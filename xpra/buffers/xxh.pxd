# This file is part of Xpra.
# Copyright (C) 2015-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: language_level=3

#cdef unsigned long long xxh64(const void* input, size_t length, unsigned long long seed) nogil
cdef unsigned long long xxh3(const void* input, size_t length) nogil
