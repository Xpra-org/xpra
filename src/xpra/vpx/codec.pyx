# This file is part of Parti.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from libc.stdlib cimport free

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    ctypedef void** const_void_pp "const void**"
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

ctypedef unsigned char uint8_t
ctypedef void vpx_codec_ctx_t
ctypedef void vpx_image_t
cdef extern from "vpxlib.h":
    void* xmemalign(size_t size)
    void xmemfree(void* ptr)

    vpx_codec_ctx_t* init_encoder(int width, int height)
    void clean_encoder(vpx_codec_ctx_t *context)
    vpx_image_t* csc_image_rgb2yuv(vpx_codec_ctx_t *ctx, uint8_t *input, int stride)
    int csc_image_yuv2rgb(vpx_codec_ctx_t *ctx, uint8_t *input[3], int stride[3], uint8_t **out, int *outsz, int *outstride) nogil
    int compress_image(vpx_codec_ctx_t *ctx, vpx_image_t *image, uint8_t **out, int *outsz) nogil

    vpx_codec_ctx_t* init_decoder(int width, int height, int use_swscale)
    void clean_decoder(vpx_codec_ctx_t *context)
    int decompress_image(vpx_codec_ctx_t *context, uint8_t *input, int size, uint8_t *(*out)[3], int *outsize, int (*outstride)[3])

""" common superclass for Decoder and Encoder """
cdef class xcoder:
    cdef vpx_codec_ctx_t *context
    cdef int width
    cdef int height

    def init(self, width, height):
        self.width = width
        self.height = height

    def is_closed(self):
        return self.context==NULL

    def get_type(self):
        return  "vpx"

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height


cdef class Decoder(xcoder):

    def init_context(self, width, height, use_swscale, options):
        self.init(width, height)
        self.context = init_decoder(width, height, use_swscale)

    def clean(self):
        if self.context!=NULL:
            clean_decoder(self.context)
            self.context = NULL

    def decompress_image_to_yuv(self, input, options):
        cdef uint8_t *dout[3]
        cdef int outsize
        cdef int outstrides[3]
        cdef unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int i = 0
        assert self.context!=NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        i = decompress_image(self.context, buf, buf_len, &dout, &outsize, &outstrides)
        if i!=0:
            return i, [0, 0, 0], ["", "", ""]
        doutvY = (<char *>dout[0])[:self.height * outstrides[0]]
        doutvU = (<char *>dout[1])[:self.height * outstrides[1]]
        doutvV = (<char *>dout[2])[:self.height * outstrides[2]]
        out = [doutvY, doutvU, doutvV]
        strides = [outstrides[0], outstrides[1], outstrides[2]]
        return  i, strides, out

    def get_pixel_format(self, csc_pixel_format):
        #we only support 420 at present
        assert csc_pixel_format==-1
        #see xpra.codec_constants: YUV420P
        return 420

    def decompress_image_to_rgb(self, input, options):
        cdef uint8_t *yuvplanes[3]
        cdef uint8_t *dout
        cdef int outsize                    #@DuplicatedSignature
        cdef int yuvstrides[3]
        cdef int outstride
        cdef unsigned char * buf = NULL     #@DuplicatedSignature
        cdef Py_ssize_t buf_len = 0         #@DuplicatedSignature
        cdef int i = 0                      #@DuplicatedSignature
        assert self.context!=NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        i = decompress_image(self.context, buf, buf_len, &yuvplanes, &outsize, &yuvstrides)
        if i!=0:
            return i, None
        with nogil:
            i = csc_image_yuv2rgb(self.context, yuvplanes, yuvstrides, &dout, &outsize, &outstride)
        if i!=0:
            return i, None
        return  i, (<char *>dout)[:outsize], outstride


cdef class Encoder(xcoder):
    cdef int frames

    def init_context(self, width, height, options):    #@DuplicatedSignature
        self.init(width, height)
        self.context = init_encoder(width, height)
        self.frames = 0

    def clean(self):                        #@DuplicatedSignature
        if self.context!=NULL:
            clean_encoder(self.context)
            self.context = NULL

    def compress_image(self, input, rowstride, options):
        cdef vpx_image_t *pic_in = NULL
        cdef uint8_t *pic_buf = NULL
        cdef Py_ssize_t pic_buf_len = 0
        assert self.context!=NULL
        #colourspace conversion with gil held:
        PyObject_AsReadBuffer(input, <const_void_pp> &pic_buf, &pic_buf_len)
        pic_in = csc_image_rgb2yuv(self.context, pic_buf, rowstride)
        assert pic_in!=NULL, "colourspace conversion failed"
        return self.do_compress_image(pic_in), {"frame" : self.frames}

    cdef do_compress_image(self, vpx_image_t *pic_in):
        #actual compression (no gil):
        cdef int i
        cdef uint8_t *cout
        cdef int coutsz
        with nogil:
            i = compress_image(self.context, pic_in, &cout, &coutsz)
        if i!=0:
            return None
        coutv = (<char *>cout)[:coutsz]
        self.frames += 1
        return  coutv

    def set_encoding_speed(self, int pct):
        return

    def set_encoding_quality(self, int pct):
        return
