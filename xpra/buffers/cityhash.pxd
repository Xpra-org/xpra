# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uint64_t, uint8_t

ctypedef unsigned int size_t

cdef uint64_t cityhash64(uint8_t *data, size_t length) noexcept nogil
