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
    if (ap % 4)!=0 or (bp % 4)!=0:
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


def hybi_unmask(mask, data):
    assert len(mask)==4, "hybi_unmask invalid mask length %i" % len(mask)
    cdef Py_ssize_t mlen = 0, dlen = 0
    cdef uintptr_t mp
    cdef uintptr_t dp
    cdef uintptr_t op
    assert object_as_buffer(mask, <const void **> &mp, &mlen)==0, "cannot get buffer pointer for %s" % type(mask)
    assert object_as_buffer(data, <const void **> &dp, &dlen)==0, "cannot get buffer pointer for %s" % type(data)
    assert mlen==4
    cdef MemBuf out_buf = getbuf(dlen)
    op = <uintptr_t> out_buf.get_mem()
    cdef unsigned char *mcbuf = <unsigned char *> mp
    cdef unsigned char *dcbuf = <unsigned char *> dp
    cdef unsigned char *ocbuf = <unsigned char *> op
    cdef uint32_t *mbuf = <uint32_t*> mp
    cdef uint32_t *dbuf = <uint32_t*> dp
    cdef uint32_t *obuf = <uint32_t*> op
    cdef uint32_t mask_value = mbuf[0]
    cdef unsigned int i, j, steps, char_steps
    if (dp % 4)!=0:
        #unaligned access, use byte at a time slow path:
        char_steps = dlen
        for 0 <= i < char_steps:
            ocbuf[i] = dcbuf[i] ^ mcbuf[i%4]
    else:
        #do 4 bytes at a time:
        steps = dlen // 4
        if steps>0:
            for 0 <= i < steps:
                obuf[i] = dbuf[i] ^ mask_value
        #bytes at a time again at the end:
        char_steps = dlen % 4
        if char_steps>0:
            for 0 <= i < char_steps:
                j = dlen-char_steps+i
                ocbuf[j] = dcbuf[j] ^ mcbuf[i]
    return memoryview(out_buf)
