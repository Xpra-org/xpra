# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#gcc -pthread -shared -O0 build/temp.linux-x86_64-2.7/xpra/x264/codec.o xpra/x264/x264lib.o -L/usr/lib64 -lx264 -lavcodec -lswscale -lpthread -lpython2.7 -o build/lib.linux-x86_64-2.7/xpra/x264/codec.so

from libc.stdlib cimport free

cdef extern from "string.h":
    void * memcpy ( void * destination, void * source, size_t num )
    void * memset ( void * ptr, int value, size_t num )

cdef extern from "stdlib.h":
    int posix_memalign (void **memptr, size_t alignment, size_t size)

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    ctypedef void** const_void_pp "const void**"
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

ctypedef unsigned char uint8_t
ctypedef void x264lib_ctx
ctypedef void x264_picture_t
cdef extern from "x264lib.h":
    x264lib_ctx* init_encoder(int width, int height)
    void clean_encoder(x264lib_ctx *context)
    x264_picture_t* csc_image_rgb2yuv(x264lib_ctx *ctx, uint8_t *input, int stride)
    int compress_image(x264lib_ctx *ctx, x264_picture_t *pic_in, uint8_t **out, int *outsz) nogil

    x264lib_ctx* init_decoder(int width, int height)
    void clean_decoder(x264lib_ctx *context)
    int decompress_image(x264lib_ctx *context, uint8_t *input, int size, uint8_t *(*out)[3], int *outsize, int (*outstride)[3]) nogil
    int csc_image_yuv2rgb(x264lib_ctx *ctx, uint8_t *input[3], int stride[3], uint8_t **out, int *outsz, int *outstride) nogil
    void change_encoding_speed(x264lib_ctx *context, int increase)


ENCODERS = {}
DECODERS = {}


""" common superclass for Decoder and Encoder """
cdef class xcoder:
    cdef x264lib_ctx *context
    cdef int width
    cdef int height

    def init(self, width, height):
        self.init_context(width, height)
        assert self.context, "failed to initialize context"
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

    def init_context(self, width, height):
        self.context = init_decoder(width, height)

    def clean(self):
        if self.context!=NULL:
            clean_decoder(self.context)
            free(self.context)
            self.context = NULL

    def decompress_image_to_yuv(self, input):
        cdef uint8_t *dout[3]
        cdef int outsize
        cdef int outstrides[3]
        cdef unsigned char * padded_buf = NULL
        cdef unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        assert self.context!=NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        i = posix_memalign(<void **> &padded_buf, 32, buf_len+32)
        if i!=0:
            return i, [0, 0, 0], ["", "", ""]
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 32)
        with nogil:
            i = decompress_image(self.context, buf, buf_len, &dout, &outsize, &outstrides)
        if i!=0:
            return i, [0, 0, 0], ["", "", ""]
        doutvY = (<char *>dout[0])[:self.height * outstrides[0]]
        doutvU = (<char *>dout[1])[:self.height * outstrides[1]]
        doutvV = (<char *>dout[2])[:self.height * outstrides[2]]
        out = [doutvY, doutvU, doutvV]
        strides = [outstrides[0], outstrides[1], outstrides[2]]
        return  i, strides, out

    def decompress_image_to_rgb(self, input):
        cdef uint8_t *yuvplanes[3]
        cdef uint8_t *dout
        cdef int outsize
        cdef int yuvstrides[3]
        cdef int outstride
        cdef unsigned char * padded_buf = NULL
        cdef unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        assert self.context!=NULL
        assert self.last_image==NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        i = posix_memalign(<void **> &padded_buf, 32, buf_len+32)
        if i!=0:
            return i, 0, ""
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 32)
        with nogil:
            i = decompress_image(self.context, padded_buf, buf_len, &yuvplanes, &outsize, &yuvstrides)
            if i==0:
                i = csc_image_yuv2rgb(self.context, yuvplanes, yuvstrides, &dout, &outsize, &outstride)
            free(padded_buf)
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

    def init_context(self, width, height):
        self.context = init_encoder(width, height)

    def clean(self):
        if self.context!=NULL:
            clean_encoder(self.context)
            free(self.context)
            self.context = NULL

    def compress_image(self, input, rowstride):
        cdef x264_picture_t *pic_in = NULL
        cdef uint8_t *cout
        cdef int coutsz
        cdef uint8_t *buf = NULL
        cdef Py_ssize_t buf_len = 0
        assert self.context!=NULL
        #colourspace conversion with gil held:
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        pic_in = csc_image_rgb2yuv(self.context, buf, rowstride)
        assert pic_in!=NULL, "colourspace conversion failed"
        #actual compression (no gil):
        with nogil:
            i = compress_image(self.context, pic_in, &cout, &coutsz)
        if i!=0:
            return i, 0, ""
        coutv = (<char *>cout)[:coutsz]
        return  i, coutsz, coutv

    def increase_encoding_speed(self):
        change_encoding_speed(self.context, 1)

    def decrease_encoding_speed(self):
        change_encoding_speed(self.context, -1)
