/**
 * This file is part of Xpra.
 * Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include "Python.h"

//Before Python 3.3, use PyMemoryView_FromBuffer
//MAJOR<<24 + MINOR<<16 + MICRO<<8
#if PY_VERSION_HEX<=0x3030000
PyObject *_memory_as_pybuffer(void *ptr, Py_ssize_t buf_len, int readonly) {
    Py_buffer pybuf;
    Py_ssize_t shape[] = {buf_len};
    int ret;
    if (readonly)
        ret = PyBuffer_FillInfo(&pybuf, NULL, ptr, buf_len, 0, PyBUF_SIMPLE);
    else
        ret = PyBuffer_FillInfo(&pybuf, NULL, ptr, buf_len, 0, PyBUF_WRITABLE);
    if (ret!=0)
        return NULL;
    pybuf.format = "B";
    pybuf.shape = shape;
    return PyMemoryView_FromBuffer(&pybuf);
}
#else
PyObject *_memory_as_pybuffer(void *ptr, Py_ssize_t buf_len, int readonly) {
	return PyMemoryView_FromMemory(ptr, buf_len, readonly);
}
#endif

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
