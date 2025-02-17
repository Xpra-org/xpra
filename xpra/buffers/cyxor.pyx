# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.common import SizedBuffer
#cython: wraparound=False, boundscheck=False

from libc.stdint cimport uint32_t, uintptr_t   # pylint: disable=syntax-error
from xpra.buffers.membuf cimport getbuf, MemBuf
from libc.string cimport memset


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS


def xor_str(a: SizedBuffer, b: SizedBuffer) -> memoryview:
    if len(a) != len(b):
        raise ValueError("cyxor cannot xor strings of different lengths (%s:%s vs %s:%s)" % (type(a), len(a), type(b), len(b)))
    cdef Py_buffer py_bufa
    memset(&py_bufa, 0, sizeof(Py_buffer))
    if PyObject_GetBuffer(a, &py_bufa, PyBUF_ANY_CONTIGUOUS):
        raise ValueError(f"failed to read pixel data from {type(a)}")
    cdef Py_buffer py_bufb
    memset(&py_bufb, 0, sizeof(Py_buffer))
    if PyObject_GetBuffer(b, &py_bufb, PyBUF_ANY_CONTIGUOUS):
        PyBuffer_Release(&py_bufa)
        raise ValueError(f"failed to read pixel data from {type(b)}")
    cdef Py_ssize_t alen = py_bufa.len
    cdef Py_ssize_t blen = py_bufb.len
    if alen != blen:
        PyBuffer_Release(&py_bufa)
        PyBuffer_Release(&py_bufb)
        raise RuntimeError(f"python or cython bug? buffers don't have the same length?")
    cdef MemBuf out_buf = getbuf(alen)
    cdef uintptr_t op = <uintptr_t> out_buf.get_mem()
    cdef unsigned char *acbuf = <unsigned char *> py_bufa.buf
    cdef unsigned char *bcbuf = <unsigned char *> py_bufb.buf
    cdef unsigned char *ocbuf = <unsigned char *> op
    cdef uint32_t *obuf = <uint32_t*> op
    cdef uint32_t *abuf = <uint32_t*> py_bufa.buf
    cdef uint32_t *bbuf = <uint32_t*> py_bufb.buf
    cdef unsigned int i, j, steps, char_steps
    if (alen % 4) != 0:
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
    return memoryview(out_buf).toreadonly()
