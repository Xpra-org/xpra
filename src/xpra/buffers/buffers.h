/**
 * This file is part of Xpra.
 * Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include "Python.h"

PyObject *_memory_as_pybuffer(void* ptr, Py_ssize_t buf_len, int readonly);
int _object_as_buffer(PyObject *obj, const void ** buffer, Py_ssize_t * buffer_len);
int _object_as_write_buffer(PyObject *obj, void ** buffer, Py_ssize_t * buffer_len);
