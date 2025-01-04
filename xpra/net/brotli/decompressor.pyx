# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uint8_t, uint32_t
from xpra.buffers.membuf cimport MemBuf, getbuf
from typing import Tuple, Dict

from xpra.common import MAX_DECOMPRESSED_SIZE
from xpra.log import Logger
log = Logger("brotli")


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "brotli/decode.h":
    ctypedef enum BrotliDecoderResult:
        # Decoding error, e.g. corrupted input or memory allocation problem
        BROTLI_DECODER_RESULT_ERROR
        # Decoding successfully completed
        BROTLI_DECODER_RESULT_SUCCESS
        # Partially done; should be called again with more input
        BROTLI_DECODER_RESULT_NEEDS_MORE_INPUT
        # Partially done; should be called again with more output
        BROTLI_DECODER_RESULT_NEEDS_MORE_OUTPUT

    ctypedef void BrotliDecoderState
    ctypedef void* brotli_alloc_func
    ctypedef void* brotli_free_func

    ctypedef int BrotliDecoderErrorCode

    BrotliDecoderErrorCode BrotliDecoderGetErrorCode(const BrotliDecoderState* state)
    const char* BrotliDecoderErrorString(BrotliDecoderErrorCode c)
    uint32_t BrotliDecoderVersion()

    BrotliDecoderState* BrotliDecoderCreateInstance(brotli_alloc_func alloc_func,
                                                    brotli_free_func free_func,
                                                    void* opaque)

    void BrotliDecoderDestroyInstance(BrotliDecoderState* state)

    # Decompresses the input stream to the output stream
    BrotliDecoderResult BrotliDecoderDecompressStream(BrotliDecoderState * state,
                                                      size_t * available_in, const uint8_t ** next_in,
                                                      size_t * available_out, uint8_t ** next_out,
                                                      size_t * total_out) nogil

    int BrotliDecoderHasMoreOutput(const BrotliDecoderState* state)
    const uint8_t* BrotliDecoderTakeOutput(BrotliDecoderState* state, size_t* size)
    int BrotliDecoderIsUsed(const BrotliDecoderState* state)
    int BrotliDecoderIsFinished(const BrotliDecoderState* state)


RESULT_STR : Dict[BrotliDecoderResult, str] = {
    BROTLI_DECODER_RESULT_ERROR : "error",
    BROTLI_DECODER_RESULT_SUCCESS   : "success",
    BROTLI_DECODER_RESULT_NEEDS_MORE_INPUT : "needs-more-input",
    BROTLI_DECODER_RESULT_NEEDS_MORE_OUTPUT : "needs-more-output",
}


def get_version() -> Tuple[int, int, int]:
    cdef uint32_t bv = BrotliDecoderVersion()
    cdef unsigned int major = bv >> 24
    cdef unsigned int minor = (bv >> 12) & 0xFFF
    cdef unsigned int patch = bv & 0xFFF
    return (major, minor, patch)


def decompress(data, maxsize=MAX_DECOMPRESSED_SIZE) -> bytes:
    cdef const uint8_t *in_ptr = NULL
    cdef size_t available_in = 0
    cdef MemBuf out_buf = getbuf(512*1024, True)
    cdef size_t available_out = 0
    cdef uint8_t *out_ptr = NULL
    cdef size_t total_out = 0
    cdef size_t decoded = 0

    cdef BrotliDecoderState* state = NULL
    cdef Py_buffer in_buf
    cdef BrotliDecoderResult r
    chunks = []

    if PyObject_GetBuffer(data, &in_buf, PyBUF_ANY_CONTIGUOUS):
        raise ValueError("failed to read data from %s" % type(data))
    in_ptr = <const uint8_t*> in_buf.buf
    available_in = in_buf.len
    log("brotli.decompress(%i bytes, %i)", available_in, maxsize)
    try:
        state = BrotliDecoderCreateInstance(NULL, NULL, NULL)
        assert state!=NULL, "failed to allocate a brotli decoder instance"
        while True:
            available_out = len(out_buf)
            out_ptr = <uint8_t*> out_buf.get_mem()
            with nogil:
                r = BrotliDecoderDecompressStream(state,
                                                  &available_in, &in_ptr,
                                                  &available_out, &out_ptr,
                                                  &total_out)
            log("BrotliDecoderDecompressStream(..)=%s", RESULT_STR.get(r, r))
            if total_out>maxsize:
                raise ValueError("brotli decompression would exceed maximum size allowed %i" % maxsize)
            if r==BROTLI_DECODER_RESULT_ERROR:
                raise ValueError("brotli decoder error")
            if r==BROTLI_DECODER_RESULT_NEEDS_MORE_INPUT:
                if available_in<=0:
                    raise ValueError("brotli decompressor expected more input data")
                continue
            assert r==BROTLI_DECODER_RESULT_NEEDS_MORE_OUTPUT or r==BROTLI_DECODER_RESULT_SUCCESS, "unknown return value %i" % r
            decoded = len(out_buf) - available_out
            assert decoded>0, "decoder returned no data"
            out_ptr = <uint8_t*> out_buf.get_mem()
            b = out_ptr[:decoded]
            chunks.append(b)
            if r==BROTLI_DECODER_RESULT_SUCCESS:
                break
    finally:
        PyBuffer_Release(&in_buf)
        if state:
            BrotliDecoderDestroyInstance(state)
    del out_buf
    if len(chunks) == 1:
        return chunks[0]
    return b"".join(chunks)
