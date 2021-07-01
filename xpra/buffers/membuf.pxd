# This file is part of Xpra.
# Copyright (C) 2015-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: language_level=3

from cpython.buffer cimport PyBuffer_FillInfo   #pylint: disable=syntax-error

cdef MemBuf getbuf(size_t l)
cdef MemBuf padbuf(size_t l, size_t padding)
cdef MemBuf makebuf(void *p, size_t l)

cdef buffer_context(object obj)

ctypedef void dealloc_callback(const void *p, size_t l, void *arg)


cdef void *memalign(size_t size) nogil


cdef class MemBuf:
    cdef const void *p
    cdef size_t l
    cdef dealloc_callback *dealloc_cb_p
    cdef void *dealloc_cb_arg

    cdef const void *get_mem(self)

