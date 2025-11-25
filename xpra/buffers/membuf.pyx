# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
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

from cpython.buffer cimport PyBuffer_FillInfo    # pylint: disable=syntax-error
from libc.stdlib cimport free
from libc.string cimport memset, memcpy
from libc.stdint cimport uintptr_t


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "memalign.h":
    void *xmemalign(size_t size) nogil
    void xmemfree(void *ptr) nogil
    int MEMALIGN_ALIGNMENT


cdef void memfree(void *p) noexcept nogil:
    xmemfree(p)


cdef void free_buf(const void *p, size_t l, void *arg) noexcept nogil:
    xmemfree(<void *>p)


cdef void free_mem(const void *p, size_t l, void *arg) noexcept nogil:
    free(<void *>p)


cdef MemBuf getbuf(size_t l, int readonly=1):
    cdef const void *p = xmemalign(l)
    if p == NULL:
        raise MemoryError(f"failed to allocate {l} bytes of memory")
    return MemBuf_init(p, l, &free_buf, NULL, readonly)


cdef MemBuf padbuf(size_t l, size_t padding, int readonly=1):
    cdef const void *p = xmemalign(l+padding)
    if p == NULL:
        raise MemoryError(f"failed to allocate {l} bytes of memory")
    return MemBuf_init(p, l, &free_buf, NULL, readonly)


cdef MemBuf makebuf(void *p, size_t l, int readonly=1):
    """
    wraps the given memory as a `MemBuf`,
    it will be freed using `free()`
    """
    if p == NULL:
        raise ValueError(f"invalid NULL buffer pointer")
    return MemBuf_init(p, l, &free_mem, NULL, readonly)


cdef MemBuf wrapbuf(void *p, size_t l, int readonly=1):
    if p == NULL:
        raise ValueError(f"invalid NULL buffer pointer")
    return MemBuf_init(p, l, NULL, NULL, readonly)


cdef void *memalign(size_t size) noexcept nogil:
    return xmemalign(size)


def get_membuf(size_t l, int readonly=1) -> MemBuf:
    return getbuf(l, readonly)


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
        PyBuffer_FillInfo(view, self, <void *>self.p, self.l, self.readonly, flags)

    def __releasebuffer__(self, Py_buffer *view):
        pass

    def __dealloc__(self):
        cdef dealloc_callback *cb = self.dealloc_cb_p
        if cb != NULL:
            self.dealloc_cb_p = NULL
            cb(self.p, self.l, self.dealloc_cb_arg)


# Call this instead of constructing a MemBuf directly.  The __cinit__
# and __init__ methods can only take Python objects, so the real
# constructor is here.  See:
# https://mail.python.org/pipermail/cython-devel/2012-June/002734.html
cdef MemBuf MemBuf_init(const void *p, size_t l,
                        dealloc_callback *dealloc_cb_p,
                        void *dealloc_cb_arg,
                        int readonly=1):
    cdef MemBuf ret = MemBuf()
    ret.readonly = readonly
    ret.p = p
    ret.l = l
    ret.dealloc_cb_p = dealloc_cb_p
    ret.dealloc_cb_arg = dealloc_cb_arg
    return ret


cdef class BufferContext:
    cdef Py_buffer py_buf
    cdef object obj

    def __init__(self, obj):
        if not obj:
            raise ValueError(f"invalid buffer object {obj!r} evaluates to False ({type(obj)}")
        self.obj = obj
        memset(&self.py_buf, 0, sizeof(Py_buffer))

    def __enter__(self):
        if self.py_buf.buf != NULL:
            raise RuntimeError("invalid state: buffer has already been obtained")
        if PyObject_GetBuffer(self.obj, &self.py_buf, PyBUF_ANY_CONTIGUOUS):
            raise RuntimeError(f"failed to access buffer of {type(self.obj)}")
        return self

    def __exit__(self, *_args):
        if self.py_buf.buf == NULL:
            raise RuntimeError("invalid state: no buffer")
        PyBuffer_Release(&self.py_buf)

    def is_readonly(self) -> bool:
        if self.py_buf.buf == NULL:
            raise RuntimeError("invalid state: no buffer")
        return bool(self.py_buf.readonly)

    def __int__(self):
        if self.py_buf.buf == NULL:
            raise RuntimeError("invalid state: no buffer")
        return int(<uintptr_t> self.py_buf.buf)

    def __len__(self):
        return self.py_buf.len

    def __repr__(self):
        return "BufferContext(%s)" % self.obj


cdef class MemBufContext:
    cdef MemBuf membuf

    def __init__(self, membuf):
        if not isinstance(membuf, MemBuf):
            raise ValueError(f"{membuf!r} is not a MemBuf instance: {type(membuf)}")
        self.membuf = membuf

    def is_readonly(self) -> bool:
        return self.membuf.readonly

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.membuf = None

    def __int__(self):
        return self.membuf.get_mem_ptr()

    def __len__(self):
        return len(self.membuf)

    def __repr__(self):
        return "MemBufContext(%s)" % self.membuf


cdef object buffer_context(object obj):
    if obj is None:
        raise ValueError(f"no buffer")
    if len(obj)==0:
        raise ValueError(f"empty {type(obj)} buffer")
    if isinstance(obj, MemBuf):
        return MemBufContext(obj)
    return BufferContext(obj)
