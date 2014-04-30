# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# Wrapper for PyObject_AsReadBuffer
# (so we can more easily replace it with "new-style buffers")

cdef extern from "Python.h":
    ctypedef int Py_ssize_t

    object PyBuffer_FromMemory(void *ptr, Py_ssize_t size)
    object PyBuffer_FromReadWriteMemory(void *ptr, Py_ssize_t size)

    int PyObject_AsReadBuffer(object obj, const void ** buffer, Py_ssize_t * buffer_len) except -1
    int PyObject_AsWriteBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1


def get_version():
    return 0

cdef object memory_as_pybuffer(void* ptr, Py_ssize_t buf_len, int readonly):
    if readonly:
        return PyBuffer_FromMemory(ptr, buf_len)
    return PyBuffer_FromReadWriteMemory(ptr, buf_len)


cdef int object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len):
    return PyObject_AsReadBuffer(obj, buffer, buffer_len)

cdef int object_as_write_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len):
    return PyObject_AsWriteBuffer(obj, buffer, buffer_len)
