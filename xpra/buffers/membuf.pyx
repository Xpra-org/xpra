# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2015-2021 Antoine Martin <antoine@xpra.org>
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

#cython: wraparound=False

from cpython.buffer cimport PyBuffer_FillInfo   #pylint: disable=syntax-error
from libc.stdlib cimport free
from libc.string cimport memset, memcpy
from libc.stdint cimport uintptr_t

cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "memalign.h":
    void *xmemalign(size_t size) nogil
    int MEMALIGN_ALIGNMENT


cdef void free_buf(const void *p, size_t l, void *arg):
    free(<void *>p)

cdef MemBuf getbuf(size_t l):
    cdef const void *p = xmemalign(l)
    assert p!=NULL, "failed to allocate %i bytes of memory" % l
    return MemBuf_init(p, l, &free_buf, NULL)

cdef MemBuf padbuf(size_t l, size_t padding):
    cdef const void *p = xmemalign(l+padding)
    assert p!=NULL, "failed to allocate %i bytes of memory" % l
    return MemBuf_init(p, l, &free_buf, NULL)

cdef MemBuf makebuf(void *p, size_t l):
    assert p!=NULL, "invalid NULL buffer pointer"
    return MemBuf_init(p, l, &free_buf, NULL)


cdef void *memalign(size_t size) nogil:
    return xmemalign(size)


def get_membuf(size_t l):
    return getbuf(l)


cdef class MemBuf:

    def __len__(self):
        return self.l

    def __repr__(self):
        return "MemBuf(%#x)" % (<uintptr_t> self.p)

    cdef const void *get_mem(self):
        return self.p

    def get_mem_ptr(self):
        return <uintptr_t> self.p

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


cdef class BufferContext:
    cdef Py_buffer py_buf
    cdef object obj
    def __init__(self, obj):
        self.obj = obj
        memset(&self.py_buf, 0, sizeof(Py_buffer))
    def __enter__(self):
        assert self.obj
        assert self.py_buf.buf==NULL
        if PyObject_GetBuffer(self.obj, &self.py_buf, PyBUF_ANY_CONTIGUOUS):
            raise Exception("failed to access buffer of %s" % type(self.obj))
        return self
    def __exit__(self, *_args):
        assert self.py_buf.buf!=NULL
        PyBuffer_Release(&self.py_buf)
    def __int__(self):
        assert self.py_buf.buf
        return int(<uintptr_t> self.py_buf.buf)
    def __len__(self):
        return self.py_buf.len
    def __repr__(self):
        return "BufferContext(%s)" % self.obj

cdef class MemBufContext:
    def __init__(self, membuf):
        assert isinstance(membuf, MemBuf), "%s is not a MemBuf instance: %s" % (membuf, type(membuf))
        self.membuf = membuf
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        self.membuf = None
    def __int__(self):
        return self.membuf.get_mem()
    def __len__(self):
        return len(self.membuf)
    def __repr__(self):
        return "MemBufContext(%s)" % self.membuf


cdef buffer_context(object obj):
    assert obj, "no buffer"
    if isinstance(obj, MemBuf):
        return MemBufContext(obj)
    return BufferContext(obj)
