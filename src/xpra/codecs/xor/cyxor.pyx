# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "stdlib.h":
    void* malloc(size_t __size)
    void free(void* mem)

cdef extern from "Python.h":
    ctypedef int Py_ssize_t

cdef extern from "../buffers/buffers.h":
    int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)


def xor_str(buf, xor_string):
    assert len(buf)==len(xor_string), "cannot xor strings of different lengths (cyxor)"
    cdef const unsigned char * cbuf = <unsigned char *> 0 #@DuplicatedSignature
    cdef Py_ssize_t cbuf_len = 0                    #@DuplicatedSignature
    assert object_as_buffer(buf, <const void**> &cbuf, &cbuf_len)==0
    cdef const unsigned char * xbuf = <unsigned char *> 0 #@DuplicatedSignature
    cdef Py_ssize_t xbuf_len = 0                    #@DuplicatedSignature
    assert object_as_buffer(xor_string, <const void**> &xbuf, &xbuf_len)==0
    assert cbuf_len == xbuf_len
    cdef unsigned char * out = <unsigned char *> malloc(cbuf_len)
    cdef int i                                      #@DuplicatedSignature
    try :
        for 0 <= i < cbuf_len:
            out[i] = cbuf[i] ^ xbuf[i]
        return out[:cbuf_len]
    finally:
        free(out)
