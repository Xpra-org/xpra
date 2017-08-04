# This file is part of Xpra.
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False
from __future__ import absolute_import

from xpra.buffers.membuf cimport getbuf, MemBuf
from xpra.buffers.membuf cimport object_as_buffer


def xor_str(buf, xor):
    assert len(buf)==len(xor), "cyxor cannot xor strings of different lengths (%s:%s vs %s:%s)" % (type(buf), len(buf), type(xor), len(xor))
    cdef const unsigned char * cbuf                 #@DuplicatedSignature
    cdef Py_ssize_t cbuf_len = 0                    #@DuplicatedSignature
    assert object_as_buffer(buf, <const void**> &cbuf, &cbuf_len)==0, "cannot get buffer pointer for %s: %s" % (type(buf), buf)
    cdef const unsigned char * xbuf                 #@DuplicatedSignature
    cdef Py_ssize_t xbuf_len = 0                    #@DuplicatedSignature
    assert object_as_buffer(xor, <const void**> &xbuf, &xbuf_len)==0, "cannot get buffer pointer for %s: %s" % (type(xor), xor)
    assert cbuf_len == xbuf_len, "python or cython bug? buffers don't have the same length?"
    cdef MemBuf out_buf = getbuf(cbuf_len)
    cdef unsigned char *obuf = <unsigned char*> out_buf.get_mem()
    cdef int i                                      #@DuplicatedSignature
    for 0 <= i < cbuf_len:
        obuf[i] = cbuf[i] ^ xbuf[i]
    return memoryview(out_buf)
