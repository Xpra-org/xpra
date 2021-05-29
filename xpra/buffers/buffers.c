/**
 * This file is part of Xpra.
 * Copyright (C) 2014-2021 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include "Python.h"

PyObject *_memory_as_pybuffer(void *ptr, Py_ssize_t buf_len, int readonly) {
	return PyMemoryView_FromMemory(ptr, buf_len, readonly);
}

int _object_as_buffer(PyObject *obj, const void ** buffer, Py_ssize_t * buffer_len) {
    Py_buffer *rpybuf;
    if (PyMemoryView_Check(obj)) {
        rpybuf = PyMemoryView_GET_BUFFER(obj);
        if (rpybuf->buf==NULL)
            return -1;
        buffer[0] = rpybuf->buf;
        *buffer_len = rpybuf->len;
        return 0;
    }
    return PyObject_AsReadBuffer(obj, buffer, buffer_len);
}

int _object_as_write_buffer(PyObject *obj, void ** buffer, Py_ssize_t * buffer_len) {
    Py_buffer *wpybuf;
    if (PyMemoryView_Check(obj)) {
        wpybuf = PyMemoryView_GET_BUFFER(obj);
        if (wpybuf->buf==NULL)
            return -1;
        buffer[0] = wpybuf->buf;
        *buffer_len = wpybuf->len;
        return 0;
    }
    return PyObject_AsWriteBuffer(obj, buffer, buffer_len);
}
