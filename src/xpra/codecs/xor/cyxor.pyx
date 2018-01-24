# This file is part of Xpra.
# Copyright (C) 2012-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False
from __future__ import absolute_import

from libc.stdint cimport uint32_t, uintptr_t
from xpra.buffers.membuf cimport getbuf, object_as_buffer, MemBuf


def xor_str(a, b):
    assert len(a)==len(b), "cyxor cannot xor strings of different lengths (%s:%s vs %s:%s)" % (type(a), len(a), type(b), len(b))
    cdef Py_ssize_t alen = 0, blen = 0
    cdef uintptr_t ap
    cdef uintptr_t bp
    cdef uintptr_t op
    assert object_as_buffer(a, <const void **> &ap, &alen)==0, "cannot get buffer pointer for %s" % type(a)
    assert object_as_buffer(b, <const void **> &bp, &blen)==0, "cannot get buffer pointer for %s" % type(b)
    assert alen == blen, "python or cython bug? buffers don't have the same length?"
    cdef MemBuf out_buf = getbuf(alen)
    op = <uintptr_t> out_buf.get_mem()
    cdef unsigned char *acbuf = <unsigned char *> ap
    cdef unsigned char *bcbuf = <unsigned char *> bp
    cdef unsigned char *ocbuf = <unsigned char *> op
    cdef uint32_t *obuf = <uint32_t*> op
    cdef uint32_t *abuf = <uint32_t*> ap
    cdef uint32_t *bbuf = <uint32_t*> bp
    cdef unsigned int i, j, steps, char_steps
    if (ap % 4)!=0 or (bp % 4!=0):
        #unaligned access, use byte at a time slow path:
        char_steps = alen
        for 0 <= i < char_steps:
            ocbuf[i] = acbuf[i] ^ bcbuf[i]
    else:
        #do 4 bytes at a time:
        steps = alen // 4
        if steps>0:
            for 0 <= i < steps:
                obuf[i] = abuf[i] ^ bbuf[i]
        #bytes at a time again at the end:
        char_steps = alen % 4
        if char_steps>0:
            for 0 <= i < char_steps:
                j = alen-char_steps+i
                ocbuf[j] = acbuf[j] ^ bcbuf[j]
    return memoryview(out_buf)
