# This file is part of Xpra.
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False
from __future__ import absolute_import

from libc.stdint cimport uint64_t
from xpra.buffers.membuf cimport getbuf, object_as_buffer, MemBuf


def xor_str(a, b):
    assert len(a)==len(b), "cyxor cannot xor strings of different lengths (%s:%s vs %s:%s)" % (type(a), len(a), type(b), len(b))
    cdef uint64_t *abuf
    cdef uint64_t *bbuf
    cdef Py_ssize_t alen = 0, blen = 0
    assert object_as_buffer(a, <const void**> &abuf, &alen)==0, "cannot get buffer pointer for %s" % type(a)
    assert object_as_buffer(b, <const void**> &bbuf, &blen)==0, "cannot get buffer pointer for %s" % type(b)
    assert alen == blen, "python or cython bug? buffers don't have the same length?"
    cdef MemBuf out_buf = getbuf(alen)
    cdef uint64_t *obuf = <uint64_t*> out_buf.get_mem()
    #64 bits at a time (8 bytes):
    cdef unsigned int steps = alen//8
    cdef unsigned int i,j
    for 0 <= i < steps:
        obuf[i] = abuf[i] ^ bbuf[i]
    #only used for the few remaining bytes at the end:
    cdef unsigned int char_steps = alen % 8
    cdef unsigned char *acbuf
    cdef unsigned char *bcbuf
    cdef unsigned char *ocbuf
    if char_steps>0:
        acbuf = <unsigned char *> abuf
        bcbuf = <unsigned char *> bbuf
        ocbuf = <unsigned char *> obuf
        for 0 <= i < char_steps:
            j = steps*8 + i
            ocbuf[j] = acbuf[j] ^ bcbuf[j]
    return memoryview(out_buf)
