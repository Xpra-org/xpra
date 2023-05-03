# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import struct
from libc.stdint cimport uintptr_t
from xpra.buffers.membuf cimport MemBuf, getbuf

from xpra.log import Logger
log = Logger("lz4")


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "lz4_compat.h":
    int LZ4_versionNumber()
    int LZ4_MAX_INPUT_SIZE

    ctypedef struct LZ4_stream_t:
        pass

    int LZ4_compressBound(int inputSize)
    void LZ4_resetStream_fast(LZ4_stream_t* stream)
    int LZ4_compress_fast_continue(LZ4_stream_t* stream,
                                   const char* src, char* dst,
                                   int srcSize, int dstCapacity, int acceleration) nogil

    int LZ4_decompress_safe(const char* src, char* dst, int compressedSize, int dstCapacity) nogil


def get_version():
    cdef int v = LZ4_versionNumber()
    return v//10000, (v//100) % 100, v % 100


cdef class compressor:
    cdef LZ4_stream_t state

    def __init__(self):
        LZ4_resetStream_fast(&self.state)

    def bound(self, int size):
        return LZ4_compressBound(size)

    def compress(self, data, int acceleration=1, int max_size=0, int store_size=True):
        cdef Py_buffer in_buf
        if PyObject_GetBuffer(data, &in_buf, PyBUF_ANY_CONTIGUOUS):
            raise ValueError("failed to read data from %s" % type(data))
        if in_buf.len>LZ4_MAX_INPUT_SIZE:
            log("input is too large")
            PyBuffer_Release(&in_buf)
            return None
        if max_size<=0:
            max_size = LZ4_compressBound(in_buf.len)
        cdef int size_header = 0
        if store_size:
            size_header = 4
        cdef MemBuf out_buf = getbuf(size_header+max_size, False)
        mem = memoryview(out_buf)
        if store_size:
            struct.pack_into(b"@I", mem, 0, in_buf.len)
        cdef const char *in_ptr = <const char *> in_buf.buf
        cdef char *out_ptr = <char *> ((<uintptr_t> out_buf.get_mem())+size_header)
        cdef int r
        with nogil:
            r = LZ4_compress_fast_continue(&self.state, in_ptr, out_ptr, in_buf.len, max_size-size_header, acceleration)
        if r<=0:
            log("LZ4_compress_fast_continue failed for input size %i and output buffer size %i", in_buf.len, max_size)
            return None
        PyBuffer_Release(&in_buf)
        return mem[:(size_header+r)]

def compress(data, acceleration=1):
    c = compressor()
    return c.compress(data, acceleration)

def decompress(data, int max_size=0, int size=0):
    cdef int size_header = 0
    if size==0:
        size = struct.unpack_from(b"@I", data[:4])[0]
        size_header = 4
    if max_size>0 and size>max_size:
        raise ValueError("data would overflow max-size %i" % max_size)
    if size>LZ4_MAX_INPUT_SIZE:
        raise ValueError("data would overflow lz4 max input size %i" % LZ4_MAX_INPUT_SIZE)
    cdef Py_buffer in_buf
    if PyObject_GetBuffer(data, &in_buf, PyBUF_ANY_CONTIGUOUS):
        raise ValueError("failed to read data from %s" % type(data))
    cdef MemBuf out_buf = getbuf(size)
    cdef char *in_ptr = <char*> ((<uintptr_t> in_buf.buf) + size_header)
    cdef char *out_ptr = <char *> out_buf.get_mem()
    cdef int l = <int> in_buf.len
    cdef int r
    with nogil:
        r = LZ4_decompress_safe(in_ptr, out_ptr, l-size_header, size)
    PyBuffer_Release(&in_buf)
    if r<=0:
        log("LZ4_decompress_safe failed for input size %i", in_buf.len)
        return None
    return memoryview(out_buf)[:r]
