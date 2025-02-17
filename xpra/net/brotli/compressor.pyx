# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uint8_t, uint32_t
from xpra.buffers.membuf cimport MemBuf, getbuf
from typing import Tuple

from xpra.common import SizedBuffer
from xpra.log import Logger
log = Logger("brotli")


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "brotli/encode.h":
    ctypedef enum BrotliEncoderMode:
        BROTLI_MODE_GENERIC
        BROTLI_MODE_TEXT
        BROTLI_MODE_FONT
    ctypedef enum BrotliEncoderOperation:
        BROTLI_OPERATION_PROCESS
        BROTLI_OPERATION_FLUSH
        BROTLI_OPERATION_FINISH
        BROTLI_OPERATION_EMIT_METADATA
    ctypedef enum BrotliEncoderParameter:
        BROTLI_PARAM_MODE
        BROTLI_PARAM_QUALITY
        BROTLI_PARAM_LGWIN
        BROTLI_PARAM_LGBLOCK
        BROTLI_PARAM_DISABLE_LITERAL_CONTEXT_MODELING
        BROTLI_PARAM_SIZE_HINT
        BROTLI_PARAM_LARGE_WINDOW
        BROTLI_PARAM_NPOSTFIX
        BROTLI_PARAM_NDIRECT
        BROTLI_PARAM_STREAM_OFFSET

    ctypedef void BrotliEncoderState
    ctypedef void* brotli_alloc_func
    ctypedef void* brotli_free_func
    ctypedef int BROTLI_BOOL

    uint32_t BrotliEncoderVersion()

    BrotliEncoderState* BrotliEncoderCreateInstance(brotli_alloc_func alloc_func,
                                                    brotli_free_func free_func,
                                                    void* opaque)
    void BrotliEncoderDestroyInstance(BrotliEncoderState* state)

    size_t BrotliEncoderMaxCompressedSize(size_t input_size)

    BROTLI_BOOL BrotliEncoderCompress(int quality, int lgwin,
                                      BrotliEncoderMode mode, size_t input_size,
                                      const uint8_t *input_buffer,
                                      size_t* encoded_size,
                                      uint8_t *encoded_buffer) nogil

    BROTLI_BOOL BrotliEncoderCompressStream(BrotliEncoderState* state,
                                            BrotliEncoderOperation op, size_t* available_in,
                                            const uint8_t** next_in, size_t* available_out, uint8_t** next_out,
                                            size_t* total_out) nogil

    BROTLI_BOOL BrotliEncoderIsFinished(BrotliEncoderState* state)
    BROTLI_BOOL BrotliEncoderHasMoreOutput(BrotliEncoderState* state)


def get_version() -> Tuple[int, int, int]:
    cdef uint32_t bv = BrotliEncoderVersion()
    cdef unsigned int major = bv >> 24
    cdef unsigned int minor = (bv >> 12) & 0xFFF
    cdef unsigned int patch = bv & 0xFFF
    return (major, minor, patch)


DEF BROTLI_MIN_QUALITY = 0
DEF BROTLI_MAX_QUALITY = 11
DEF BROTLI_DEFAULT_WINDOW = 22


def compress(data, int quality=1) -> memoryview:
    #clamp to >2 so that we can use BrotliEncoderMaxCompressedSize:
    quality = max(2, min(BROTLI_MAX_QUALITY, quality))
    cdef size_t max_size = BrotliEncoderMaxCompressedSize(len(data))

    cdef MemBuf out_buf = getbuf(max_size, True)
    cdef uint8_t *out = <uint8_t *> out_buf.get_mem()

    cdef Py_buffer in_buf
    if PyObject_GetBuffer(data, &in_buf, PyBUF_ANY_CONTIGUOUS):
        raise ValueError(f"failed to read data from {type(data)}")
    cdef const uint8_t *in_ptr = <const uint8_t*> in_buf.buf

    cdef size_t out_size = max_size
    cdef int r
    log("brotli.compress(%i bytes, %i) into %i byte buffer", in_buf.len, quality, out_size)
    try:
        with nogil:
            r = BrotliEncoderCompress(quality, BROTLI_DEFAULT_WINDOW,
                                      BROTLI_MODE_GENERIC,
                                      in_buf.len, in_ptr,
                                      &out_size, out)
    finally:
        PyBuffer_Release(&in_buf)
    if not r:
        raise ValueError(f"brotli compression failed: {r}")
    return memoryview(out[:out_size]).toreadonly()
