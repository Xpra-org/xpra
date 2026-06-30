# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: wraparound=False

from typing import Tuple

from libc.stdint cimport uint32_t, uint8_t

from xpra.buffers.membuf cimport MemBuf, getbuf
from xpra.common import SizedBuffer
from xpra.net.compression import MAX_DECOMPRESSED_SIZE
from xpra.log import Logger

log = Logger("zstd")


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS


cdef extern from "zstd.h":
    ctypedef struct ZSTD_CCtx:
        pass
    ctypedef struct ZSTD_DCtx:
        pass
    ctypedef struct ZSTD_CStream:
        pass
    ctypedef struct ZSTD_DStream:
        pass

    ctypedef struct ZSTD_inBuffer:
        const void* src
        size_t size
        size_t pos

    ctypedef struct ZSTD_outBuffer:
        void* dst
        size_t size
        size_t pos

    ctypedef enum ZSTD_EndDirective:
        ZSTD_e_continue
        ZSTD_e_flush
        ZSTD_e_end

    uint32_t ZSTD_versionNumber()
    const char* ZSTD_versionString()

    size_t ZSTD_compressBound(size_t srcSize)
    unsigned ZSTD_isError(size_t result)
    const char* ZSTD_getErrorName(size_t result)
    unsigned long long ZSTD_getFrameContentSize(const void *src, size_t srcSize)

    ZSTD_CCtx* ZSTD_createCCtx()
    size_t ZSTD_freeCCtx(ZSTD_CCtx* cctx)
    size_t ZSTD_compressCCtx(ZSTD_CCtx* cctx,
                             void* dst, size_t dstCapacity,
                             const void* src, size_t srcSize,
                             int compressionLevel) nogil

    ZSTD_DCtx* ZSTD_createDCtx()
    size_t ZSTD_freeDCtx(ZSTD_DCtx* dctx)
    size_t ZSTD_decompressDCtx(ZSTD_DCtx* dctx,
                               void* dst, size_t dstCapacity,
                               const void* src, size_t srcSize) nogil

    ZSTD_CStream* ZSTD_createCStream()
    size_t ZSTD_freeCStream(ZSTD_CStream* zcs)
    size_t ZSTD_initCStream(ZSTD_CStream* zcs, int compressionLevel)
    size_t ZSTD_compressStream2(ZSTD_CStream* cctx,
                                ZSTD_outBuffer* output,
                                ZSTD_inBuffer* input,
                                ZSTD_EndDirective endOp) nogil
    size_t ZSTD_flushStream(ZSTD_CStream* zcs, ZSTD_outBuffer* output) nogil
    size_t ZSTD_CStreamOutSize()

    ZSTD_DStream* ZSTD_createDStream()
    size_t ZSTD_freeDStream(ZSTD_DStream* zds)
    size_t ZSTD_initDStream(ZSTD_DStream* zds)
    size_t ZSTD_decompressStream(ZSTD_DStream* zds, ZSTD_outBuffer* output, ZSTD_inBuffer* input) nogil
    size_t ZSTD_DStreamOutSize()


DEF ZSTD_CONTENTSIZE_UNKNOWN = 18446744073709551615
DEF ZSTD_CONTENTSIZE_ERROR = 18446744073709551614


cdef inline void raise_zstd_error(size_t result, str what):
    cdef bytes name = <bytes> ZSTD_getErrorName(result)
    raise ValueError(f"{what}: {name.decode('latin1')}")


def get_version() -> Tuple[int, int, int]:
    cdef uint32_t v = ZSTD_versionNumber()
    return v // 10000, (v // 100) % 100, v % 100


def get_version_string() -> str:
    return (<bytes> ZSTD_versionString()).decode("latin1")


cdef class compressor:
    cdef ZSTD_CCtx* state

    def __cinit__(self):
        self.state = ZSTD_createCCtx()
        if self.state == NULL:
            raise MemoryError("failed to allocate a zstd compression context")

    def __dealloc__(self):
        if self.state != NULL:
            ZSTD_freeCCtx(self.state)
            self.state = NULL

    def bound(self, size_t size) -> int:
        cdef size_t bound = ZSTD_compressBound(size)
        if ZSTD_isError(bound):
            raise_zstd_error(bound, "ZSTD_compressBound")
        return bound

    def compress(self, data: SizedBuffer, int level=1) -> memoryview:
        cdef Py_buffer in_buf
        cdef Py_ssize_t input_size
        cdef size_t bound
        cdef MemBuf out_buf
        cdef const uint8_t* in_ptr
        cdef uint8_t* out_ptr
        cdef size_t r

        if PyObject_GetBuffer(data, &in_buf, PyBUF_ANY_CONTIGUOUS):
            raise ValueError(f"failed to read data from {type(data)}")
        try:
            input_size = in_buf.len
            bound = ZSTD_compressBound(in_buf.len)
            if ZSTD_isError(bound):
                raise_zstd_error(bound, "ZSTD_compressBound")
            out_buf = getbuf(bound, False)
            in_ptr = <const uint8_t*> in_buf.buf
            out_ptr = <uint8_t*> out_buf.get_mem()
            with nogil:
                r = ZSTD_compressCCtx(self.state, out_ptr, bound, in_ptr, in_buf.len, level)
        finally:
            PyBuffer_Release(&in_buf)
        if ZSTD_isError(r):
            raise_zstd_error(r, f"zstd compression failed for input size {input_size}")
        return memoryview(out_buf)[:r].toreadonly()


def compress(data: SizedBuffer, int level=1) -> memoryview:
    c = compressor()
    return c.compress(data, level)


cdef class decompressor:
    cdef ZSTD_DCtx* state

    def __cinit__(self):
        self.state = ZSTD_createDCtx()
        if self.state == NULL:
            raise MemoryError("failed to allocate a zstd decompression context")

    def __dealloc__(self):
        if self.state != NULL:
            ZSTD_freeDCtx(self.state)
            self.state = NULL

    def decompress(self, data: SizedBuffer, maxsize: int = MAX_DECOMPRESSED_SIZE) -> memoryview:
        cdef Py_buffer in_buf
        cdef Py_ssize_t input_size
        cdef const uint8_t* in_ptr
        cdef unsigned long long frame_size
        cdef MemBuf out_buf
        cdef uint8_t* out_ptr
        cdef size_t r

        if PyObject_GetBuffer(data, &in_buf, PyBUF_ANY_CONTIGUOUS):
            raise ValueError(f"failed to read data from {type(data)}")
        try:
            input_size = in_buf.len
            in_ptr = <const uint8_t*> in_buf.buf
            frame_size = ZSTD_getFrameContentSize(in_ptr, in_buf.len)
            if frame_size == ZSTD_CONTENTSIZE_ERROR:
                raise ValueError("invalid zstd frame")
            if frame_size == ZSTD_CONTENTSIZE_UNKNOWN:
                raise ValueError("zstd frame content size is unknown, use stream_decompressor")
            if frame_size > maxsize:
                raise ValueError(f"zstd decompression would exceed maximum size allowed {maxsize}")
            out_buf = getbuf(frame_size, False)
            out_ptr = <uint8_t*> out_buf.get_mem()
            with nogil:
                r = ZSTD_decompressDCtx(self.state, out_ptr, frame_size, in_ptr, in_buf.len)
        finally:
            PyBuffer_Release(&in_buf)
        if ZSTD_isError(r):
            raise_zstd_error(r, f"zstd decompression failed for input size {input_size}")
        return memoryview(out_buf)[:r].toreadonly()


cdef class stream_compressor:
    cdef ZSTD_CStream* state
    cdef int level

    def __cinit__(self, int level=1):
        self.state = ZSTD_createCStream()
        if self.state == NULL:
            raise MemoryError("failed to allocate a zstd stream compressor")
        self.level = level
        self.reset(level)

    def __dealloc__(self):
        if self.state != NULL:
            ZSTD_freeCStream(self.state)
            self.state = NULL

    def reset(self, int level=1) -> None:
        cdef size_t r = ZSTD_initCStream(self.state, level)
        if ZSTD_isError(r):
            raise_zstd_error(r, "ZSTD_initCStream")
        self.level = level

    def compress(self, data: SizedBuffer, bint end_frame=False) -> bytes:
        cdef Py_buffer in_buf
        cdef ZSTD_inBuffer input
        cdef ZSTD_outBuffer output
        cdef size_t out_size = ZSTD_CStreamOutSize()
        cdef MemBuf out_buf
        cdef uint8_t* out_ptr
        cdef size_t r
        cdef size_t produced
        cdef ZSTD_EndDirective directive = ZSTD_e_end if end_frame else ZSTD_e_continue
        chunks = []

        if out_size == 0:
            out_size = 65536
        if PyObject_GetBuffer(data, &in_buf, PyBUF_ANY_CONTIGUOUS):
            raise ValueError(f"failed to read data from {type(data)}")
        try:
            input.src = in_buf.buf
            input.size = in_buf.len
            input.pos = 0
            while True:
                out_buf = getbuf(out_size, True)
                out_ptr = <uint8_t*> out_buf.get_mem()
                output.dst = out_ptr
                output.size = out_size
                output.pos = 0
                with nogil:
                    r = ZSTD_compressStream2(self.state, &output, &input, directive)
                if ZSTD_isError(r):
                    raise_zstd_error(r, "ZSTD_compressStream2")
                produced = output.pos
                if produced:
                    chunks.append((<char*> out_ptr)[:produced])
                if input.pos >= input.size:
                    if directive == ZSTD_e_continue:
                        break
                    if r == 0:
                        break
        finally:
            PyBuffer_Release(&in_buf)
        return b"".join(chunks)

    def flush(self) -> bytes:
        cdef ZSTD_outBuffer output
        cdef size_t out_size = ZSTD_CStreamOutSize()
        cdef MemBuf out_buf
        cdef uint8_t* out_ptr
        cdef size_t r
        cdef size_t produced
        chunks = []

        if out_size == 0:
            out_size = 65536
        while True:
            out_buf = getbuf(out_size, True)
            out_ptr = <uint8_t*> out_buf.get_mem()
            output.dst = out_ptr
            output.size = out_size
            output.pos = 0
            with nogil:
                r = ZSTD_flushStream(self.state, &output)
            if ZSTD_isError(r):
                raise_zstd_error(r, "ZSTD_flushStream")
            produced = output.pos
            if produced:
                chunks.append((<char*> out_ptr)[:produced])
            if r == 0:
                break
        return b"".join(chunks)


cdef class stream_decompressor:
    cdef ZSTD_DStream* state

    def __cinit__(self):
        self.state = ZSTD_createDStream()
        if self.state == NULL:
            raise MemoryError("failed to allocate a zstd stream decompressor")
        self.reset()

    def __dealloc__(self):
        if self.state != NULL:
            ZSTD_freeDStream(self.state)
            self.state = NULL

    def reset(self) -> None:
        cdef size_t r = ZSTD_initDStream(self.state)
        if ZSTD_isError(r):
            raise_zstd_error(r, "ZSTD_initDStream")

    def decompress(self, data: SizedBuffer, maxsize: int = MAX_DECOMPRESSED_SIZE) -> bytes:
        cdef Py_buffer in_buf
        cdef ZSTD_inBuffer input
        cdef ZSTD_outBuffer output
        cdef size_t out_size = ZSTD_DStreamOutSize()
        cdef MemBuf out_buf
        cdef uint8_t* out_ptr
        cdef size_t r
        cdef size_t produced
        cdef size_t total = 0
        chunks = []

        if out_size == 0:
            out_size = 65536
        if PyObject_GetBuffer(data, &in_buf, PyBUF_ANY_CONTIGUOUS):
            raise ValueError(f"failed to read data from {type(data)}")
        try:
            input.src = in_buf.buf
            input.size = in_buf.len
            input.pos = 0
            while True:
                out_buf = getbuf(out_size, True)
                out_ptr = <uint8_t*> out_buf.get_mem()
                output.dst = out_ptr
                output.size = out_size
                output.pos = 0
                with nogil:
                    r = ZSTD_decompressStream(self.state, &output, &input)
                if ZSTD_isError(r):
                    raise_zstd_error(r, "ZSTD_decompressStream")
                produced = output.pos
                if produced:
                    total += produced
                    if total > maxsize:
                        raise ValueError(f"zstd decompression would exceed maximum size allowed {maxsize}")
                    chunks.append((<char*> out_ptr)[:produced])
                if r == 0 and input.pos >= input.size:
                    break
                if input.pos >= input.size and produced == 0:
                    raise ValueError("zstd decompressor expected more input data")
        finally:
            PyBuffer_Release(&in_buf)
        return b"".join(chunks)


def decompress(data: SizedBuffer, maxsize: int = MAX_DECOMPRESSED_SIZE):
    cdef Py_buffer in_buf
    cdef const uint8_t* in_ptr
    cdef unsigned long long frame_size

    if PyObject_GetBuffer(data, &in_buf, PyBUF_ANY_CONTIGUOUS):
        raise ValueError(f"failed to read data from {type(data)}")
    try:
        in_ptr = <const uint8_t*> in_buf.buf
        frame_size = ZSTD_getFrameContentSize(in_ptr, in_buf.len)
    finally:
        PyBuffer_Release(&in_buf)
    if frame_size not in (ZSTD_CONTENTSIZE_UNKNOWN, ZSTD_CONTENTSIZE_ERROR):
        d = decompressor()
        return d.decompress(data, maxsize)
    sd = stream_decompressor()
    return sd.decompress(data, maxsize)
