/**
 * This file is part of Xpra.
 * Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include "Python.h"

int _object_as_buffer(PyObject *obj, const void ** buffer, Py_ssize_t * buffer_len);
