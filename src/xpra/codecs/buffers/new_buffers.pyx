# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject

    ctypedef struct PyMemoryViewObject:
        pass

    ctypedef struct Py_buffer:
        void *buf
        Py_ssize_t len
        int readonly
        char *format
        int ndim
        Py_ssize_t *shape
        Py_ssize_t *strides
        Py_ssize_t *suboffsets
        Py_ssize_t itemsize
        void *internal

    cdef enum:
        PyBUF_SIMPLE
        PyBUF_WRITABLE
        PyBUF_FORMAT
        PyBUF_ANY_CONTIGUOUS

    #void PyBuffer_Release(Py_buffer *view)
    int PyMemoryView_Check(object obj)
    object PyMemoryView_FromBuffer(Py_buffer *info)
    Py_buffer *PyMemoryView_GET_BUFFER(object obj)

    int PyBuffer_FillInfo(Py_buffer *view, object obj, void *buf, Py_ssize_t len, int readonly, int infoflags) except -1
    int PyObject_GetBuffer(object, Py_buffer *, int) except -1

    #fallback for non memoryviews:
    int PyObject_AsReadBuffer(object obj, const void ** buffer, Py_ssize_t * buffer_len) except -1


cdef object memory_as_pybuffer(void* ptr, Py_ssize_t buf_len, int readonly):
    cdef Py_buffer pybuf
    cdef Py_ssize_t *shape = [buf_len]
    if readonly:
        assert PyBuffer_FillInfo(&pybuf, None, ptr, buf_len, False, PyBUF_SIMPLE)==0
    else:
        assert PyBuffer_FillInfo(&pybuf, None, ptr, buf_len, False, PyBUF_WRITABLE)==0
    pybuf.format = "B"
    pybuf.shape = shape
    return PyMemoryView_FromBuffer(&pybuf)


cdef int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len):
    cdef Py_buffer *pybuf
    if PyMemoryView_Check(obj):
        #log.info("found memory view!")
        pybuf = PyMemoryView_GET_BUFFER(obj)
        assert pybuf.buf!=NULL
        buffer[0] = pybuf.buf
        return 0
        #log.info("using py_buffer @ %#x", <unsigned long> py_buffer.buf)
    return PyObject_AsReadBuffer(obj, buffer, buffer_len)
