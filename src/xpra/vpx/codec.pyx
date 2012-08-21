# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
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
    vpx_codec_ctx_t* init_encoder(int width, int height)
    void clean_encoder(vpx_codec_ctx_t *context)
    vpx_image_t* csc_image_rgb2yuv(vpx_codec_ctx_t *ctx, uint8_t *input, int stride)
    int csc_image_yuv2rgb(vpx_codec_ctx_t *ctx, uint8_t *input[3], int stride[3], uint8_t **out, int *outsz, int *outstride) nogil
    int compress_image(vpx_codec_ctx_t *ctx, vpx_image_t *image, uint8_t **out, int *outsz) nogil

    vpx_codec_ctx_t* init_decoder(int width, int height)
    void clean_decoder(vpx_codec_ctx_t *context)
    int decompress_image(vpx_codec_ctx_t *context, uint8_t *input, int size, uint8_t *(*out)[3], int *outsize, int (*outstride)[3])


NOGIL = os.environ.get("XPRA_VPX_NOGIL", "").lower() not in ("0", "no", "false")

ENCODERS = {}
DECODERS = {}


""" common superclass for Decoder and Encoder """
cdef class xcoder:
    cdef vpx_codec_ctx_t *context
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

    def init_context(self, width, height):
        self.context = NULL


cdef class Decoder(xcoder):
    cdef uint8_t *last_image

    def init_context(self, width, height, options):
        self.init(width, height)
        self.context = init_decoder(width, height)

    def clean(self):
        if self.context!=NULL:
            clean_decoder(self.context)
            self.context = NULL

    def decompress_image_to_yuv(self, input):
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

    def decompress_image_to_rgb(self, input, options):
        cdef uint8_t *yuvplanes[3]
        cdef uint8_t *dout
        cdef int outsize
        cdef int yuvstrides[3]
        cdef int outstride
        cdef unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int i = 0
        assert self.context!=NULL
        assert self.last_image==NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        i = decompress_image(self.context, buf, buf_len, &yuvplanes, &outsize, &yuvstrides)
        if i!=0:
            return i, 0, ""
        if NOGIL:
            with nogil:
                i = csc_image_yuv2rgb(self.context, yuvplanes, yuvstrides, &dout, &outsize, &outstride)
        else:
            i = csc_image_yuv2rgb(self.context, yuvplanes, yuvstrides, &dout, &outsize, &outstride)
        if i!=0:
            return i, 0, ""
        self.last_image = dout
        doutv = (<char *>dout)[:outsize]
        return  i, outstride, doutv

    def free_image(self):
        assert self.last_image!=NULL
        free(self.last_image)
        self.last_image = NULL


cdef class Encoder(xcoder):

    def init_context(self, width, height, supports_options):
        self.init(width, height)
        self.context = init_encoder(width, height)

    def clean(self):
        if self.context!=NULL:
            clean_encoder(self.context)
            self.context = NULL

    def get_client_options(self, options):
        #we don't use any..
        return  {}

    def compress_image(self, input, rowstride, options):
        cdef vpx_image_t *pic_in = NULL
        cdef uint8_t *buf = NULL
        cdef Py_ssize_t buf_len = 0
        assert self.context!=NULL
        #colourspace conversion with gil held:
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        pic_in = csc_image_rgb2yuv(self.context, buf, rowstride)
        assert pic_in!=NULL, "colourspace conversion failed"
        return self.do_compress_image(pic_in)

    cdef do_compress_image(self, vpx_image_t *pic_in):
        #actual compression (no gil):
        cdef int i
        cdef uint8_t *cout
        cdef int coutsz
        if NOGIL:
            with nogil:
                i = compress_image(self.context, pic_in, &cout, &coutsz)
        else:
            i = compress_image(self.context, pic_in, &cout, &coutsz)
        if i!=0:
            return i, 0, ""
        coutv = (<char *>cout)[:coutsz]
        return  i, coutsz, coutv

    def set_encoding_speed(self, pct):
        return

    def set_encoding_quality(self, pct):
        return
