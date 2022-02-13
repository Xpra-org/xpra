# This file is part of Xpra.
# Copyright (C) 2021-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from xpra.log import Logger
log = Logger("decoder", "spng")

from xpra.net.compression import Compressed
from xpra.codecs.codec_debug import may_save_image
from xpra.codecs.spng.spng cimport (
    SPNG_VERSION_MAJOR, SPNG_VERSION_MINOR, SPNG_VERSION_PATCH,
    SPNG_CTX_ENCODER, 
    SPNG_INTERLACE_NONE,
    SPNG_ENCODE_FINALIZE,
    SPNG_FILTER_CHOICE, SPNG_FILTER_CHOICE_NONE, SPNG_FILTER_CHOICE_SUB,
    SPNG_ENCODE_TO_BUFFER,
    SPNG_IMG_COMPRESSION_LEVEL,
    SPNG_IMG_MEM_LEVEL,
    SPNG_IMG_COMPRESSION_STRATEGY,
    SPNG_TEXT_WINDOW_BITS,
    SPNG_FMT_PNG,
    SPNG_COLOR_TYPE_GRAYSCALE, SPNG_COLOR_TYPE_TRUECOLOR, SPNG_COLOR_TYPE_GRAYSCALE_ALPHA, SPNG_COLOR_TYPE_TRUECOLOR_ALPHA,
    spng_ctx, spng_ihdr, spng_strerror,
    spng_ctx_new, spng_ctx_free,
    spng_set_option, spng_set_ihdr,
    spng_encode_image, spng_get_png_buffer,
    )
from libc.stdint cimport uintptr_t, uint32_t, uint8_t
from xpra.buffers.membuf cimport makebuf, MemBuf, buffer_context #pylint: disable=syntax-error


cdef extern from "zconf.h":
    int MAX_MEM_LEVEL

cdef extern from "zlib.h":
    int Z_HUFFMAN_ONLY


def get_version():
    return (SPNG_VERSION_MAJOR, SPNG_VERSION_MINOR, SPNG_VERSION_PATCH)

def get_type():
    return "spng"

def get_encodings():
    return ("png", "png/L")

def get_error_str(int r):
    b = spng_strerror(r)
    return b.decode()

def check_error(int r, msg):
    if r:
        log_error(r, msg)
    return r

def log_error(int r, msg):
    log.error("Error: %s", msg)
    log.error(" code %i: %s", r, get_error_str(r))

INPUT_FORMATS = "RGBA", "RGB"

def encode(coding, image, options=None):
    assert coding in ("png", "png/L")
    options = options or {}
    cdef int grayscale = options.get("grayscale", 0) or coding=="png/L"
    cdef int speed = options.get("speed", 50)
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    cdef int rowstride = image.get_rowstride()
    cdef int scaled_width = options.get("scaled-width", width)
    cdef int scaled_height = options.get("scaled-height", height)
    cdef char resize = scaled_width!=width or scaled_height!=height

    rgb_format = image.get_pixel_format()
    alpha = options.get("alpha", True)
    if rgb_format not in INPUT_FORMATS or (resize and len(rgb_format)!=4) or rowstride!=width*len(rgb_format) or grayscale:
        #best to restride before byte-swapping to trim extra unused data:
        if rowstride!=width*len(rgb_format):
            image.restride(width*len(rgb_format))
        input_formats = INPUT_FORMATS
        if grayscale:
            input_formats = ("BGRX", "BGRA")
        if rgb_format not in input_formats:
            from xpra.codecs.argb.argb import argb_swap         #@UnresolvedImport
            if not argb_swap(image, input_formats, supports_transparency=alpha):
                log("spng: argb_swap failed to convert %s to a suitable format: %s" % (
                    rgb_format, input_formats))
            else:
                log("spng converted %s to %s", rgb_format, image)
                rgb_format = image.get_pixel_format()
        rowstride = image.get_rowstride()

    if resize:
        from xpra.codecs.argb.scale import scale_image
        image = scale_image(image, scaled_width, scaled_height)
        log("spng scaled image: %s", image)

    pixels = image.get_pixels()
    if grayscale:
        from xpra.codecs.argb.argb import bgrx_to_l, bgra_to_la
        if alpha:
            pixels = bgra_to_la(pixels)
            rgb_format = "LA"
        else:
            pixels = bgrx_to_l(pixels)
            rgb_format = "L"

    cdef spng_ctx *ctx = spng_ctx_new(SPNG_CTX_ENCODER)
    if ctx==NULL:
        raise Exception("failed to instantiate an spng context")

    cdef spng_ihdr ihdr
    ihdr.width = scaled_width
    ihdr.height = scaled_height
    ihdr.bit_depth = 8
    if rgb_format=="L":
        ihdr.color_type = SPNG_COLOR_TYPE_GRAYSCALE
    elif rgb_format=="LA":
        ihdr.color_type = SPNG_COLOR_TYPE_GRAYSCALE_ALPHA
    elif rgb_format=="RGBA":
        ihdr.color_type = SPNG_COLOR_TYPE_TRUECOLOR_ALPHA
    elif rgb_format=="RGB":
        ihdr.color_type = SPNG_COLOR_TYPE_TRUECOLOR
    else:
        raise Exception("unsupported input pixel format %s" % rgb_format)

    ihdr.compression_method = 0
    ihdr.filter_method = 0
    ihdr.interlace_method = SPNG_INTERLACE_NONE
    if check_error(spng_set_ihdr(ctx, &ihdr),
                   "failed to set encode-to-buffer option"):
        spng_ctx_free(ctx)
        return None

    cdef int clevel = 1
    if check_error(spng_set_option(ctx, SPNG_IMG_COMPRESSION_LEVEL, clevel),
                   "failed to set compression level"):
        spng_ctx_free(ctx)
        return None
    if check_error(spng_set_option(ctx, SPNG_TEXT_WINDOW_BITS, 15),
                   "failed to set window bits"):
        spng_ctx_free(ctx)
        return None
    if check_error(spng_set_option(ctx, SPNG_IMG_COMPRESSION_STRATEGY, Z_HUFFMAN_ONLY),
                   "failed to set compression strategy"):
        spng_ctx_free(ctx)
        return None
    if check_error(spng_set_option(ctx, SPNG_IMG_MEM_LEVEL, MAX_MEM_LEVEL),
                   "failed to set mem level"):
        spng_ctx_free(ctx)
        return None
    cdef int filter = SPNG_FILTER_CHOICE_NONE
    if speed<30:
        filter |= SPNG_FILTER_CHOICE_SUB
    if check_error(spng_set_option(ctx, SPNG_FILTER_CHOICE, filter),
                   "failed to set filter choice"):
        spng_ctx_free(ctx)
        return None

    if check_error(spng_set_option(ctx, SPNG_ENCODE_TO_BUFFER, 1),
                   "failed to set encode-to-buffer option"):
        spng_ctx_free(ctx)
        return None

    cdef spng_format fmt = SPNG_FMT_PNG
    cdef int flags = SPNG_ENCODE_FINALIZE
    cdef size_t data_len = 0
    cdef uintptr_t data_ptr
    cdef int r = 0
    assert len(pixels)>=ihdr.width*ihdr.height*len(rgb_format), \
        "pixel buffer is too small, expected %i bytes but got %i for %ix%i '%s'" % (
        ihdr.width*ihdr.height*4, len(pixels), ihdr.width, ihdr.height, rgb_format)
    with buffer_context(pixels) as bc:
        data_ptr = <uintptr_t> int(bc)
        data_len = len(bc)
        #log("spng encode buffer %#x, len=%#x", <uintptr_t> data_ptr, data_len)
        with nogil:
            r = spng_encode_image(ctx, <const void*> data_ptr, data_len, fmt, flags)
    if check_error(r, "failed to encode image"):
        log.error(" %i bytes of %s pixel data", data_len, rgb_format)
        log.error(" for %s", image)
        spng_ctx_free(ctx)
        return None

    cdef int error
    cdef size_t png_len
    cdef void *png_data = spng_get_png_buffer(ctx, &png_len, &error)
    if check_error(error,
                   "failed get png buffer"):
        spng_ctx_free(ctx)
        return None
    if png_data==NULL:
        log.error("Error: spng buffer is NULL")
        spng_ctx_free(ctx)
        return None

    cdef membuf = makebuf(png_data, png_len)
    spng_ctx_free(ctx)
    cdata = memoryview(membuf)
    may_save_image("png", cdata)
    return coding, Compressed(coding, cdata), {}, width, height, 0, len(rgb_format)*8


def selftest(full=False):
    log("spng version %s selftest" % (get_version(),))
    from xpra.codecs.codec_checks import make_test_image
    for rgb_format in ("RGBA", "RGB", "BGRA", "BGRX"):
        image = make_test_image(rgb_format, 1024, 768)
        assert encode("png", image), "failed to encode %s" % image
