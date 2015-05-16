/**
 * This file is part of Xpra.
 * Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

// Wrapper for PyObject_AsReadBuffer
// (so we can more easily replace it with "new-style buffers")

#include "Python.h"

int get_buffer_api_version(void) {
    return 0;
}

#if (PY_VERSION_HEX < 0x02050000)
typedef int Py_ssize_t;
#endif

PyObject *memory_as_pybuffer(void *ptr, Py_ssize_t buf_len, int readonly) {
    if (readonly)
        return PyBuffer_FromMemory(ptr, buf_len);
    return PyBuffer_FromReadWriteMemory(ptr, buf_len);
}

int object_as_buffer(PyObject *obj, const void ** buffer, Py_ssize_t * buffer_len) {
    return PyObject_AsReadBuffer(obj, buffer, buffer_len);
}

int object_as_write_buffer(PyObject *obj, void ** buffer, Py_ssize_t * buffer_len) {
    return PyObject_AsWriteBuffer(obj, buffer, buffer_len);
}
