# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from xpra.log import Logger
log = Logger("decoder", "spng")

from libc.stdint cimport uint32_t, uint8_t
from xpra.buffers.membuf cimport getbuf, MemBuf #pylint: disable=syntax-error


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "spng.h":
    enum SPNG_FMT:
        SPNG_FMT_RGBA8
        SPNG_FMT_RGBA16
        SPNG_FMT_RGB8

    enum spng_color_type:
        SPNG_COLOR_TYPE_GRAYSCALE
        SPNG_COLOR_TYPE_TRUECOLOR
        SPNG_COLOR_TYPE_INDEXED
        SPNG_COLOR_TYPE_GRAYSCALE_ALPHA
        SPNG_COLOR_TYPE_TRUECOLOR_ALPHA

    ctypedef struct spng_ctx:
        pass

    cdef struct spng_ihdr:
        uint32_t height
        uint32_t width
        uint8_t bit_depth
        uint8_t color_type
        uint8_t compression_method
        uint8_t filter_method
        uint8_t interlace_method

    const char *spng_version_string()
    const char *spng_strerror(int err)
    spng_ctx *spng_ctx_new(int flags)
    void spng_ctx_free(spng_ctx *ctx)
    int spng_get_ihdr(spng_ctx *ctx, spng_ihdr *ihdr)
    int spng_set_png_buffer(spng_ctx *ctx, const void *buf, size_t size) nogil
    int spng_decoded_image_size(spng_ctx *ctx, int fmt, size_t *len) nogil
    int spng_decode_image(spng_ctx *ctx, void *out, size_t len, int fmt, int flags) nogil


COLOR_TYPE_STR = {
    SPNG_COLOR_TYPE_GRAYSCALE       : "GRAYSCALE",
    SPNG_COLOR_TYPE_TRUECOLOR       : "TRUECOLOR",
    SPNG_COLOR_TYPE_INDEXED         : "INDEXED",
    SPNG_COLOR_TYPE_GRAYSCALE_ALPHA : "GRAYSCALE_ALPHA",
    SPNG_COLOR_TYPE_TRUECOLOR_ALPHA : "TRUECOLOR_ALPHA",
    }


def get_version():
    return spng_version_string()

def get_encodings():
    return ("png", )

def get_error_str(int r):
    s = spng_strerror(r)
    return str(s)

def check_error(int r, msg):
    if r:
        log_error(r, msg)
    return r

def log_error(int r, msg):
    log.error("Error: %s", msg)
    log.error(" code %i: %s", r, get_error_str(r))

def decompress(data):
    cdef spng_ctx *ctx = spng_ctx_new(0)
    if ctx==NULL:
        raise Exception("failed to instantiate an spng context")

    cdef Py_buffer py_buf
    if PyObject_GetBuffer(data, &py_buf, PyBUF_ANY_CONTIGUOUS):
        spng_ctx_free(ctx)
        raise Exception("failed to read compressed data from %s" % type(data))

    cdef int r
    def close():
        PyBuffer_Release(&py_buf)
        spng_ctx_free(ctx)

    if check_error(spng_set_png_buffer(ctx, py_buf.buf, py_buf.len),
                   "failed to set png buffer"):
        close()
        return None

    cdef spng_ihdr ihdr
    if check_error(spng_get_ihdr(ctx, &ihdr),
                   "failed to get ihdr"):
        close()
        return None

    log("ihdr: %ix%i-%i, color-type=%#x, compression-method=%#x, filter-method=%#x, interlace-method=%#x",
        ihdr.width, ihdr.height, ihdr.bit_depth, ihdr.color_type,
        ihdr.compression_method, ihdr.filter_method, ihdr.interlace_method)

    cdef size_t out_size
    cdef int fmt
    if ihdr.color_type==SPNG_COLOR_TYPE_TRUECOLOR:
        fmt = SPNG_FMT_RGB8
        rgb_format = "RGB"
    elif ihdr.color_type==SPNG_COLOR_TYPE_TRUECOLOR_ALPHA:
        fmt = SPNG_FMT_RGBA8
        rgb_format = "RGBA"
    else:
        raise ValueError("cannot handle color type %s" % COLOR_TYPE_STR.get(ihdr.color_type, ihdr.color_type))

    if check_error(spng_decoded_image_size(ctx, fmt, &out_size),
                   "failed to get decoded image size"):
        close()
        return None

    cdef MemBuf membuf = getbuf(out_size)
    if check_error(spng_decode_image(ctx, <void *> membuf.get_mem(), out_size, fmt, 0),
                   "failed to decode image"):
        close()
        return None

    close()
    return memoryview(membuf), rgb_format, ihdr.width, ihdr.height 


def selftest(full=False):
    log("spng selftest")
    import binascii
    from xpra.codecs.codec_checks import TEST_PICTURES  #pylint: disable=import-outside-toplevel
    for hexdata in TEST_PICTURES["png"]:
        cdata = binascii.unhexlify(hexdata)
        assert decompress(cdata)
