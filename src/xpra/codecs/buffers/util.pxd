# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


cdef extern from "Python.h":
    ctypedef int Py_ssize_t

cdef object memory_as_pybuffer(void* ptr, Py_ssize_t buf_len, int readonly)
cdef int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)
