# This file is part of Xpra.
# Copyright (C) 2021-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from libc.stdint cimport uintptr_t, uint32_t, uint8_t

cdef extern from "spng.h":
    int SPNG_VERSION_MAJOR
    int SPNG_VERSION_MINOR
    int SPNG_VERSION_PATCH

    int SPNG_CTX_ENCODER

    int SPNG_FILTER_NONE
    int SPNG_INTERLACE_NONE

    int SPNG_DECODE_TRNS

    enum spng_format:
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
        spng_color_type color_type
        uint8_t compression_method
        uint8_t filter_method
        uint8_t interlace_method

    enum spng_encode_flags:
        SPNG_ENCODE_PROGRESSIVE
        SPNG_ENCODE_FINALIZE

    enum spng_filter_choice:
        SPNG_DISABLE_FILTERING
        SPNG_FILTER_CHOICE_NONE
        SPNG_FILTER_CHOICE_SUB
        SPNG_FILTER_CHOICE_UP
        SPNG_FILTER_CHOICE_AVG
        SPNG_FILTER_CHOICE_PAETH
        SPNG_FILTER_CHOICE_ALL

    enum spng_option:
        SPNG_ENCODE_TO_BUFFER
        SPNG_KEEP_UNKNOWN_CHUNKS

        SPNG_IMG_COMPRESSION_LEVEL

        SPNG_IMG_WINDOW_BITS
        SPNG_IMG_MEM_LEVEL
        SPNG_IMG_COMPRESSION_STRATEGY

        SPNG_TEXT_COMPRESSION_LEVEL
        SPNG_TEXT_WINDOW_BITS
        SPNG_TEXT_MEM_LEVEL
        SPNG_TEXT_COMPRESSION_STRATEGY

        SPNG_FILTER_CHOICE

    enum spng_format:
        SPNG_FMT_RGBA8
        SPNG_FMT_RGBA16
        SPNG_FMT_RGB8
        # Partially implemented, see documentation
        SPNG_FMT_GA8
        SPNG_FMT_GA16
        SPNG_FMT_G8
        SPNG_FMT_PNG        #host-endian
        SPNG_FMT_RAW        #big-endian

    const char *spng_version_string()
    const char *spng_strerror(int err)

    spng_ctx *spng_ctx_new(int flags)
    void spng_ctx_free(spng_ctx *ctx)

    int spng_set_option(spng_ctx *ctx, spng_option option, int value)
    int spng_set_ihdr(spng_ctx *ctx, spng_ihdr *ihdr)
    int spng_encode_image(spng_ctx *ctx, const void *img, size_t len, int fmt, int flags) nogil
    void *spng_get_png_buffer(spng_ctx *ctx, size_t *len, int *error)

    int spng_get_ihdr(spng_ctx *ctx, spng_ihdr *ihdr)
    int spng_set_png_buffer(spng_ctx *ctx, const void *buf, size_t size) nogil
    int spng_decoded_image_size(spng_ctx *ctx, int fmt, size_t *len) nogil
    int spng_decode_image(spng_ctx *ctx, void *out, size_t len, int fmt, int flags) nogil
