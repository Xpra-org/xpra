# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "Python.h":
    object PyString_FromStringAndSize(char * s, int len)
    ctypedef int Py_ssize_t
    ctypedef void** const_void_pp "const void**"
    int PyObject_AsWriteBuffer(object obj,
                               void ** buffer,
                               Py_ssize_t * buffer_len) except -1
    int PyObject_AsReadBuffer(object obj,
                              void ** buffer,
                              Py_ssize_t * buffer_len) except -1


def argb_to_rgba(buf):
    # b is a Python buffer object
    cdef const unsigned long * cbuf = <unsigned long *> 0
    cdef Py_ssize_t cbuf_len = 0
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    PyObject_AsReadBuffer(buf, <const_void_pp> &cbuf, &cbuf_len)
    return argbdata_to_pixdata(cbuf, cbuf_len)

cdef argbdata_to_pixdata(const unsigned long* data, int dlen):
    if dlen <= 0:
        return None
    assert dlen % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % dlen
    import array
    # Create byte array
    b = array.array('b', '\0'* dlen)
    cdef int offset = 0
    cdef int i = 0
    cdef unsigned long rgba
    cdef unsigned long argb
    cdef char b1, b2, b3, b4
    while i < dlen/4:
        argb = data[i] & 0xffffffff
        rgba = <unsigned long> ((argb << 8) | (argb >> 24)) & 0xffffffff
        b1 = (rgba >> 24) & 0xff
        b2 = (rgba >> 16) & 0xff
        b3 = (rgba >> 8) & 0xff
        b4 = rgba & 0xff
        b[offset] = b1
        b[offset+1] = b2
        b[offset+2] = b3
        b[offset+3] = b4
        offset = offset + 4
        i = i + 1
    return b

def argb_to_rgb(buf):
    # b is a Python buffer object
    cdef unsigned long * cbuf = <unsigned long *> 0     #@DuplicateSignature
    cdef Py_ssize_t cbuf_len = 0                        #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    PyObject_AsReadBuffer(buf, <const_void_pp> &cbuf, &cbuf_len)
    return argbdata_to_rgb(cbuf, cbuf_len)

cdef argbdata_to_rgb(const unsigned long* data, int dlen):
    if dlen <= 0:
        return None
    assert dlen % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % dlen
    import array
    # Create byte array
    b = array.array('b', '\0'* (dlen/4*3))
    cdef int offset = 0                     #@DuplicateSignature
    cdef int i = 0                          #@DuplicateSignature
    cdef unsigned long rgba                 #@DuplicateSignature
    cdef unsigned long argb                 #@DuplicateSignature
    cdef char b1, b2, b3                    #@DuplicateSignature
    while i < dlen/4:
        argb = data[i] & 0xffffffff
        rgba = <unsigned long> ((argb << 8) | (argb >> 24)) & 0xffffffff
        b1 = (rgba >> 24) & 0xff
        b2 = (rgba >> 16) & 0xff
        b3 = (rgba >> 8) & 0xff
        b[offset] = b1
        b[offset+1] = b2
        b[offset+2] = b3
        offset = offset + 3
        i = i + 1
    return b


def premultiply_argb_in_place(buf):
    # b is a Python buffer object
    cdef unsigned int * cbuf = <unsigned int *> 0
    cdef Py_ssize_t cbuf_len = 0                #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    PyObject_AsWriteBuffer(buf, <void **>&cbuf, &cbuf_len)
    do_premultiply_argb_in_place(cbuf, cbuf_len)

cdef do_premultiply_argb_in_place(unsigned int * cbuf, Py_ssize_t cbuf_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data, in-place.
    cdef unsigned int a, r, g, b
    assert sizeof(int) == 4
    assert cbuf_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % cbuf_len
    cdef int i
    for 0 <= i < cbuf_len / 4:
        a = (cbuf[i] >> 24) & 0xff
        r = (cbuf[i] >> 16) & 0xff
        r = (r * a) / 255
        g = (cbuf[i] >> 8) & 0xff
        g = g * a / 255
        b = (cbuf[i] >> 0) & 0xff
        b = b * a / 255
        cbuf[i] = (a << 24) | (r << 16) | (g << 8) | (b << 0)
