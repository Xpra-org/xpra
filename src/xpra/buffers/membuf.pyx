# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2015-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#Buffer code found here:
#http://stackoverflow.com/a/28166272/428751
#Allows to return a malloced python buffer,
#which will be freed when the python object is garbage collected
#(also uses memalign to allocate the buffer)

from cpython.buffer cimport PyBuffer_FillInfo
from libc.stdlib cimport free
from libc.string cimport memcpy

cdef extern from "memalign.h":
    void *xmemalign(size_t size) nogil


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


cdef class MemBuf:

    def __len__(self):
        return self.l

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
