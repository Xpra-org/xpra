# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2015-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Memory buffers functions:
#
# 1) Buffer code found here and also similar to the Cython docs:
#    http://stackoverflow.com/a/28166272/428751
#    Allows to return a malloced python buffer,
#    which will be freed when the python object is garbage collected
#    (also uses memalign to allocate the buffer)
# 2) object to buffer conversion utility functions,
# 3) xxhash wrapper


from cpython.buffer cimport PyBuffer_FillInfo
from libc.stdlib cimport free
from libc.string cimport memcpy
from libc.stdint cimport uintptr_t

cdef extern from "memalign.h":
    void *xmemalign(size_t size) nogil
    int MEMALIGN_ALIGNMENT

cdef extern from "buffers.h":
    object _memory_as_pybuffer(void* ptr, Py_ssize_t buf_len, int readonly)
    int _object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)
    int _object_as_write_buffer(object obj, void ** buffer, Py_ssize_t * buffer_len)

cdef extern from "xxhash.h":
    ctypedef unsigned long long XXH64_hash_t
    XXH64_hash_t XXH64(const void* input, size_t length, unsigned long long seed) nogil


cdef void free_buf(const void *p, size_t l, void *arg):
    free(<void *>p)

cdef getbuf(size_t l):
    cdef const void *p = xmemalign(l)
    assert p!=NULL, "failed to allocate %i bytes of memory" % l
    return MemBuf_init(p, l, &free_buf, NULL)

cdef padbuf(size_t l, size_t padding):
    cdef const void *p = xmemalign(l+padding)
    assert p!=NULL, "failed to allocate %i bytes of memory" % l
    return MemBuf_init(p, l, &free_buf, NULL)

cdef makebuf(void *p, size_t l):
    assert p!=NULL, "invalid NULL buffer pointer"
    return MemBuf_init(p, l, &free_buf, NULL)


cdef void *memalign(size_t size) nogil:
    return xmemalign(size)


cdef object memory_as_pybuffer(void* ptr, Py_ssize_t buf_len, int readonly):
    return _memory_as_pybuffer(ptr, buf_len, readonly)

cdef int object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len):
    return _object_as_buffer(obj, buffer, buffer_len)

cdef int object_as_write_buffer(object obj, void ** buffer, Py_ssize_t * buffer_len):
    return _object_as_write_buffer(obj, buffer, buffer_len)


cdef class MemBuf:

    def __len__(self):
        return self.l

    def __repr__(self):
        return "MemBuf(%#x)" % (<uintptr_t> self.p)

    cdef const void *get_mem(self):
        return self.p

    def __getbuffer__(self, Py_buffer *view, int flags):
        PyBuffer_FillInfo(view, self, <void *>self.p, self.l, 1, flags)

    def __releasebuffer__(self, Py_buffer *view):
        pass

    def __dealloc__(self):
        if self.dealloc_cb_p != NULL:
            self.dealloc_cb_p(self.p, self.l, self.dealloc_cb_arg)

# Call this instead of constructing a MemBuf directly.  The __cinit__
# and __init__ methods can only take Python objects, so the real
# constructor is here.  See:
# https://mail.python.org/pipermail/cython-devel/2012-June/002734.html
cdef MemBuf MemBuf_init(const void *p, size_t l,
                        dealloc_callback *dealloc_cb_p,
                        void *dealloc_cb_arg):
    cdef MemBuf ret = MemBuf()
    ret.p = p
    ret.l = l
    ret.dealloc_cb_p = dealloc_cb_p
    ret.dealloc_cb_arg = dealloc_cb_arg
    return ret


cdef unsigned long long xxh64(const void* input, size_t length, unsigned long long seed) nogil:
    return XXH64(input, length, seed)
