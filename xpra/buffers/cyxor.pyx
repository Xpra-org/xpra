# This file is part of Xpra.
# Copyright (C) 2012-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False, boundscheck=False, language_level=3

from libc.stdint cimport uint32_t, uintptr_t  #pylint: disable=syntax-error
from xpra.buffers.membuf cimport getbuf, MemBuf, buffer_context
from libc.string cimport memcpy, memset


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS


def xor_str(a, b):
    assert len(a)==len(b), "cyxor cannot xor strings of different lengths (%s:%s vs %s:%s)" % (type(a), len(a), type(b), len(b))
    cdef Py_buffer py_bufa
    memset(&py_bufa, 0, sizeof(Py_buffer))
    if PyObject_GetBuffer(a, &py_bufa, PyBUF_ANY_CONTIGUOUS):
        raise Exception("failed to read pixel data from %s" % type(a))
    cdef Py_buffer py_bufb
    memset(&py_bufb, 0, sizeof(Py_buffer))
    if PyObject_GetBuffer(b, &py_bufb, PyBUF_ANY_CONTIGUOUS):
        PyBuffer_Release(&py_bufa)
        raise Exception("failed to read pixel data from %s" % type(b))
    cdef Py_ssize_t alen = py_bufa.len
    cdef Py_ssize_t blen = py_bufb.len
    if alen!=blen:
        PyBuffer_Release(&py_bufa)
        PyBuffer_Release(&py_bufb)
        raise Exception("python or cython bug? buffers don't have the same length?")
    cdef MemBuf out_buf = getbuf(alen)
    cdef uintptr_t op = <uintptr_t> out_buf.get_mem()
    cdef unsigned char *acbuf = <unsigned char *> py_bufa.buf
    cdef unsigned char *bcbuf = <unsigned char *> py_bufb.buf
    cdef unsigned char *ocbuf = <unsigned char *> op
    cdef uint32_t *obuf = <uint32_t*> op
    cdef uint32_t *abuf = <uint32_t*> py_bufa.buf
    cdef uint32_t *bbuf = <uint32_t*> py_bufb.buf
    cdef unsigned int i, j, steps, char_steps
    if (alen % 4)!=0 or (blen % 4)!=0:
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
    PyBuffer_Release(&py_bufa)
    PyBuffer_Release(&py_bufb)
    return memoryview(out_buf)


def hybi_unmask(data, unsigned int offset, unsigned int datalen):
    cdef uintptr_t mp
    with buffer_context(data) as bc:
        assert len(bc)>=offset+4+datalen, "buffer too small %i vs %i: offset=%i, datalen=%i" % (len(bc), offset+4+datalen, offset, datalen)
        mp = (<uintptr_t> int(bc))+offset
        return do_hybi_mask(mp, mp+4, datalen)

def hybi_mask(mask, data):
    with buffer_context(mask) as mbc:
        if len(mbc)<4:
            raise Exception("mask buffer too small: %i bytes" % len(mbc))
        with buffer_context(data) as dbc:
            return do_hybi_mask(<uintptr_t> int(mbc), <uintptr_t> int(dbc), len(dbc))

cdef object do_hybi_mask(uintptr_t mp, uintptr_t dp, unsigned int datalen):
    #we skip the first 'align' bytes in the output buffer,
    #to ensure that its alignment is the same as the input data buffer
    cdef unsigned int align = (<uintptr_t> dp) & 0x3
    cdef unsigned int initial_chars = (4-align) & 0x3
    cdef MemBuf out_buf = getbuf(datalen+align)
    cdef uintptr_t op = <uintptr_t> out_buf.get_mem()
    #char pointers:
    cdef unsigned char *mcbuf = <unsigned char *> mp
    cdef unsigned char *dcbuf = <unsigned char *> dp
    cdef unsigned char *ocbuf = <unsigned char *> op
    cdef unsigned int i, j
    #bytes at a time until we reach the 32-bit boundary:
    for 0 <= i < initial_chars:
        ocbuf[align+i] = dcbuf[i] ^ mcbuf[i & 0x3]
    #32-bit pointers:
    cdef uint32_t *dbuf
    cdef uint32_t *obuf
    cdef uint32_t mask_value
    cdef unsigned int uint32_steps = 0
    cdef unsigned int last_chars = 0
    if datalen>initial_chars:
        uint32_steps = (datalen-initial_chars) // 4
        if uint32_steps:
            dbuf = <uint32_t*> (dp+initial_chars)
            obuf = <uint32_t*> (op+align+initial_chars)
            mask_value = 0
            for 0 <= i < 4:
                mask_value = mask_value<<8
                mask_value += mcbuf[(3-i+initial_chars) & 0x3]
            for 0 <= i < uint32_steps:
                obuf[i] = dbuf[i] ^ mask_value
        #bytes at a time again at the end:
        last_chars = (datalen-initial_chars) & 0x3
        for 0 <= i < last_chars:
            j = datalen-last_chars+i
            ocbuf[align+j] = dcbuf[j] ^ mcbuf[j & 0x3]
    if align>0:
        return memoryview(out_buf)[align:]
    return memoryview(out_buf)
