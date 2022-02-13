# This file is part of Xpra.
# Copyright (C) 2021-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from xpra.log import Logger
log = Logger("decoder", "spng")

from xpra.codecs.spng.spng cimport (
    SPNG_VERSION_MAJOR, SPNG_VERSION_MINOR, SPNG_VERSION_PATCH,
    SPNG_CTX_ENCODER, 
    SPNG_DECODE_TRNS,
    SPNG_FMT_RGBA8, SPNG_FMT_RGBA16, SPNG_FMT_RGB8,
    SPNG_COLOR_TYPE_GRAYSCALE, SPNG_COLOR_TYPE_TRUECOLOR, SPNG_COLOR_TYPE_GRAYSCALE_ALPHA,
    SPNG_COLOR_TYPE_TRUECOLOR_ALPHA, SPNG_COLOR_TYPE_INDEXED,
    spng_ctx, spng_ihdr, spng_strerror,
    spng_ctx_new, spng_ctx_free,
    spng_get_ihdr, spng_format,
    spng_decode_image, spng_set_png_buffer, spng_decoded_image_size,
    )
from libc.stdint cimport uintptr_t, uint32_t, uint8_t
from xpra.buffers.membuf cimport getbuf, MemBuf #pylint: disable=syntax-error
from xpra.util import envint

MAX_SIZE = envint("XPRA_SPNG_MAX_SIZE", 8192*8192)


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS


COLOR_TYPE_STR = {
    SPNG_COLOR_TYPE_GRAYSCALE       : "GRAYSCALE",
    SPNG_COLOR_TYPE_TRUECOLOR       : "TRUECOLOR",
    SPNG_COLOR_TYPE_INDEXED         : "INDEXED",
    SPNG_COLOR_TYPE_GRAYSCALE_ALPHA : "GRAYSCALE_ALPHA",
    SPNG_COLOR_TYPE_TRUECOLOR_ALPHA : "TRUECOLOR_ALPHA",
    }

def get_version():
    return (SPNG_VERSION_MAJOR, SPNG_VERSION_MINOR, SPNG_VERSION_PATCH)

def get_encodings():
    return ("png", "png/L", "png/P")

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

    log("ihdr: %ix%i-%i, color-type=%s, compression-method=%#x, filter-method=%#x, interlace-method=%#x",
        ihdr.width, ihdr.height, ihdr.bit_depth, COLOR_TYPE_STR.get(ihdr.color_type, ihdr.color_type),
        ihdr.compression_method, ihdr.filter_method, ihdr.interlace_method)

    cdef int flags = 0
    cdef size_t out_size
    cdef spng_format fmt
    if ihdr.color_type==SPNG_COLOR_TYPE_TRUECOLOR:
        fmt = SPNG_FMT_RGB8
        rgb_format = "RGB"
    elif ihdr.color_type==SPNG_COLOR_TYPE_TRUECOLOR_ALPHA:
        fmt = SPNG_FMT_RGBA8
        rgb_format = "RGBA"
        flags = SPNG_DECODE_TRNS
    elif ihdr.color_type==SPNG_COLOR_TYPE_GRAYSCALE:
        fmt = SPNG_FMT_RGB8
        rgb_format = "RGB"
        flags = SPNG_DECODE_TRNS
    elif ihdr.color_type==SPNG_COLOR_TYPE_GRAYSCALE_ALPHA:
        fmt = SPNG_FMT_RGBA8
        rgb_format = "RGBA"
        flags = SPNG_DECODE_TRNS
    else:
        raise ValueError("cannot handle color type %s" % COLOR_TYPE_STR.get(ihdr.color_type, ihdr.color_type))

    if check_error(spng_decoded_image_size(ctx, fmt, &out_size),
                   "failed to get decoded image size"):
        close()
        return None
    if out_size>MAX_SIZE:
        log.error("Error: spng image size %i is too big", out_size)
        log.error(" maximum size supported is %i", MAX_SIZE)
        close()
        return None

    cdef MemBuf membuf = getbuf(out_size)
    cdef uintptr_t ptr = <uintptr_t> membuf.get_mem()
    with nogil:
        r = spng_decode_image(ctx, <void *> ptr, out_size, fmt, flags)
    if check_error(r, "failed to decode image"):
        close()
        return None

    close()
    return memoryview(membuf), rgb_format, ihdr.width, ihdr.height


def selftest(full=False):
    log("spng version %s selftest" % (get_version(),))
    import binascii
    from xpra.codecs.codec_checks import TEST_PICTURES  #pylint: disable=import-outside-toplevel
    for hexdata in TEST_PICTURES["png"]:
        cdata = binascii.unhexlify(hexdata)
        assert decompress(cdata)
