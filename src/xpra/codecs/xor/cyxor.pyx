# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "stdlib.h":
    void* malloc(size_t __size)
    void free(void* mem)


cdef extern from "../../buffers/memalign.h":
    void *xmemalign(size_t size) nogil

cdef extern from "../../buffers/buffers.h":
    int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)


def xor_str(buf, xor):
    assert len(buf)==len(xor), "cyxor cannot xor strings of different lengths (%s:%s vs %s:%s)" % (type(buf), len(buf), type(xor), len(xor))
    cdef const unsigned char * cbuf                 #@DuplicatedSignature
    cdef Py_ssize_t cbuf_len = 0                    #@DuplicatedSignature
    assert object_as_buffer(buf, <const void**> &cbuf, &cbuf_len)==0, "cannot get buffer pointer for %s: %s" % (type(buf), buf)
    cdef const unsigned char * xbuf                 #@DuplicatedSignature
    cdef Py_ssize_t xbuf_len = 0                    #@DuplicatedSignature
    assert object_as_buffer(xor, <const void**> &xbuf, &xbuf_len)==0, "cannot get buffer pointer for %s: %s" % (type(xor), xor)
    assert cbuf_len == xbuf_len, "python or cython bug? buffers don't have the same length?"
    out_bytes = bytearray(cbuf_len)
    cdef unsigned char * obuf                 #@DuplicatedSignature
    cdef Py_ssize_t obuf_len = 0                    #@DuplicatedSignature
    assert object_as_buffer(out_bytes, <const void**> &obuf, &obuf_len)==0, "cannot get buffer pointer for %s: %s" % (type(obuf), obuf)
    assert obuf_len==cbuf_len
    cdef int i                                      #@DuplicatedSignature
    for 0 <= i < cbuf_len:
        obuf[i] = cbuf[i] ^ xbuf[i]
    return out_bytes
