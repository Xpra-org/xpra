# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from libc.stdlib cimport free

cdef extern from "string.h":
    void * memcpy ( void * destination, void * source, size_t num )
    void * memset ( void * ptr, int value, size_t num )

cdef extern from *:
    ctypedef unsigned long size_t

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    ctypedef void** const_void_pp "const void**"
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

ctypedef unsigned char uint8_t
ctypedef void x264lib_ctx
ctypedef void x264_picture_t
cdef extern from "x264lib.h":
    void* xmemalign(size_t size)
    void xmemfree(void* ptr)

    x264lib_ctx* init_encoder(int width, int height, int initial_quality, int supports_csc_option)
    void clean_encoder(x264lib_ctx *context)
    x264_picture_t* csc_image_rgb2yuv(x264lib_ctx *ctx, uint8_t *input, int stride)
    int compress_image(x264lib_ctx *ctx, x264_picture_t *pic_in, uint8_t **out, int *outsz, int quality_override) nogil
    int get_encoder_pixel_format(x264lib_ctx *ctx)
    int get_encoder_quality(x264lib_ctx *ctx)
    int get_pixel_format(int csc_format)

    x264lib_ctx* init_decoder(int width, int height, int csc_fmt)
    void set_decoder_csc_format(x264lib_ctx *context, int csc_fmt)
    void clean_decoder(x264lib_ctx *context)
    int decompress_image(x264lib_ctx *context, uint8_t *input, int size, uint8_t *(*out)[3], int *outsize, int (*outstride)[3]) nogil
    int csc_image_yuv2rgb(x264lib_ctx *ctx, uint8_t *input[3], int stride[3], uint8_t **out, int *outsz, int *outstride) nogil
    void set_encoding_speed(x264lib_ctx *context, int pct)
    void set_encoding_quality(x264lib_ctx *context, int pct)


""" common superclass for Decoder and Encoder """
cdef class xcoder:
    cdef x264lib_ctx *context
    cdef int width
    cdef int height

    def init(self, width, height):
        self.width = width
        self.height = height

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):
        return  "x264"

cdef class RGBImage:
    cdef uint8_t *data
    cdef int size
    cdef int rowstride

    cdef init(self, uint8_t *data, int size, int rowstride):
        self.data = data
        self.size = size
        self.rowstride = rowstride

    cdef free(self):
        assert self.data!=NULL
        xmemfree(self.data)
        self.data = NULL

    def get_data(self):
        return (<char *>self.data)[:self.size]

    def get_size(self):
        return self.size

    def get_rowstride(self):
        return self.rowstride

    def __dealloc__(self):                  #@DuplicatedSignature
        self.free()


cdef class Decoder(xcoder):

    def init_context(self, width, height, options):
        self.init(width, height)
        csc_fmt = options.get("csc_pixel_format", -1)
        self.context = init_decoder(width, height, csc_fmt)

    def clean(self):
        if self.context!=NULL:
            clean_decoder(self.context)
            self.context = NULL

    def decompress_image_to_yuv(self, input, options):
        cdef uint8_t *dout[3]
        cdef int outsize
        cdef int outstrides[3]
        cdef unsigned char * padded_buf = NULL
        cdef unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        assert self.context!=NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        padded_buf = <unsigned char *> xmemalign(buf_len+32)
        if padded_buf==NULL:
            return 1, [0, 0, 0], ["", "", ""]
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 32)
        set_decoder_csc_format(self.context, int(options.get("csc_pixel_format", -1)))
        i = 0
        with nogil:
            i = decompress_image(self.context, buf, buf_len, &dout, &outsize, &outstrides)
        xmemfree(padded_buf)
        if i!=0:
            return i, [0, 0, 0], ["", "", ""]
        doutvY = (<char *>dout[0])[:self.height * outstrides[0]]
        doutvU = (<char *>dout[1])[:self.height * outstrides[1]]
        doutvV = (<char *>dout[2])[:self.height * outstrides[2]]
        out = [doutvY, doutvU, doutvV]
        strides = [outstrides[0], outstrides[1], outstrides[2]]
        return  i, strides, out

    def get_pixel_format(self, csc_pixel_format):
        return get_pixel_format(csc_pixel_format)

    def decompress_image_to_rgb(self, input, options):
        cdef uint8_t *yuvplanes[3]
        cdef uint8_t *dout
        cdef int outsize                        #@DuplicatedSignature
        cdef int yuvstrides[3]
        cdef int outstride
        cdef unsigned char * padded_buf = NULL  #@DuplicatedSignature
        cdef unsigned char * buf = NULL         #@DuplicatedSignature
        cdef Py_ssize_t buf_len = 0             #@DuplicatedSignature
        cdef int i = 0
        assert self.context!=NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        padded_buf = <unsigned char *> xmemalign(buf_len+32)
        if padded_buf==NULL:
            return 100, None
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 32)
        set_decoder_csc_format(self.context, int(options.get("csc_pixel_format", -1)))
        with nogil:
            i = decompress_image(self.context, padded_buf, buf_len, &yuvplanes, &outsize, &yuvstrides)
            if i==0:
                i = csc_image_yuv2rgb(self.context, yuvplanes, yuvstrides, &dout, &outsize, &outstride)
        xmemfree(padded_buf)
        if i!=0:
            return i, None
        rgb_image = RGBImage()
        rgb_image.init(dout, outsize, outstride)
        return  i, rgb_image


cdef class Encoder(xcoder):
    cdef int frames
    cdef int supports_options

    def init_context(self, width, height, supports_options):    #@DuplicatedSignature
        self.init(width, height)
        self.supports_options = supports_options
        self.context = init_encoder(width, height, 70, int(supports_options))
        self.frames = 0

    def clean(self):                        #@DuplicatedSignature
        if self.context!=NULL:
            clean_encoder(self.context)
            self.context = NULL

    def get_client_options(self, options):
        client_options = {
                "csc_pixel_format" : get_encoder_pixel_format(self.context),
                "frame" : self.frames
                }
        if "quality" in options:
            #quality was overriden via options:
            client_options["quality"] = options["quality"]
        else:
            #current quality settings:
            client_options["quality"] = get_encoder_quality(self.context)
        return  client_options

    def compress_image(self, input, rowstride, options):
        cdef x264_picture_t *pic_in = NULL
        cdef uint8_t *pic_buf = NULL
        cdef Py_ssize_t pic_buf_len = 0
        cdef int quality_override = options.get("quality", -1)
        assert self.context!=NULL
        #colourspace conversion with gil held:
        PyObject_AsReadBuffer(input, <const_void_pp> &pic_buf, &pic_buf_len)
        pic_in = csc_image_rgb2yuv(self.context, pic_buf, rowstride)
        assert pic_in!=NULL, "colourspace conversion failed"
        return self.do_compress_image(pic_in, quality_override)

    cdef do_compress_image(self, x264_picture_t *pic_in, int quality_override):
        #actual compression (no gil):
        cdef int i
        cdef uint8_t *cout
        cdef int coutsz
        with nogil:
            i = compress_image(self.context, pic_in, &cout, &coutsz, quality_override)
        if i!=0:
            return i, 0, ""
        coutv = (<char *>cout)[:coutsz]
        self.frames += 1
        return  i, coutsz, coutv

    def set_encoding_speed(self, pct):
        ipct = int(pct)
        assert ipct>=0 and ipct<=100, "invalid percentage: %s" % ipct
        set_encoding_speed(self.context, ipct)

    def set_encoding_quality(self, pct):
        ipct = int(pct)
        assert ipct>=0 and ipct<=100, "invalid percentage: %s" % ipct
        set_encoding_quality(self.context, ipct)
