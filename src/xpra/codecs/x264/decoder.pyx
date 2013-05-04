# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from libc.stdlib cimport free

from xpra.codecs.codec_constants import get_subsampling_divs

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
    void* xmemalign(size_t size) nogil
    void xmemfree(void* ptr) nogil

    int get_x264_build_no()

    x264lib_ctx* init_decoder(int width, int height, int use_swscale, int csc_fmt)
    void set_decoder_csc_format(x264lib_ctx *context, int csc_fmt)
    void clean_decoder(x264lib_ctx *context)
    int decompress_image(x264lib_ctx *context, uint8_t *input, int size, uint8_t *(*out)[3], int (*outstride)[3]) nogil
    int csc_image_yuv2rgb(x264lib_ctx *ctx, uint8_t *input[3], int stride[3], uint8_t **out, int *outsz, int *outstride) nogil
    int get_pixel_format(int csc_format)


def get_version():
    return get_x264_build_no()


cdef class Decoder:
    cdef x264lib_ctx *context
    cdef int width
    cdef int height

    def init_context(self, width, height, use_swscale, options):
        self.width = width
        self.height = height
        csc_fmt = options.get("csc_pixel_format", -1)
        self.context = init_decoder(width, height, use_swscale, csc_fmt)

    def is_closed(self):
        return self.context==NULL

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):
        return  "x264"

    def clean(self):
        if self.context!=NULL:
            clean_decoder(self.context)
            self.context = NULL

    def decompress_image_to_yuv(self, input, options):
        cdef uint8_t *dout[3]
        cdef int outstrides[3]
        cdef unsigned char * padded_buf = NULL
        cdef unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int i = 0
        assert self.context!=NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        padded_buf = <unsigned char *> xmemalign(buf_len+32)
        if padded_buf==NULL:
            return 1, [0, 0, 0], ["", "", ""]
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 32)
        csc_pixel_format = int(options.get("csc_pixel_format", -1))
        set_decoder_csc_format(self.context, csc_pixel_format)
        with nogil:
            i = decompress_image(self.context, padded_buf, buf_len, &dout, &outstrides)
        xmemfree(padded_buf)
        if i!=0:
            return i, [0, 0, 0], ["", "", ""]
        out = []
        strides = []
        pixel_format = self.get_pixel_format(csc_pixel_format)
        divs = get_subsampling_divs(pixel_format)
        for i in (0, 1, 2):
            _, dy = divs[i]
            if dy==1:
                height = self.height
            elif dy==2:
                height = (self.height+1)>>1
            else:
                raise Exception("invalid height divisor %s" % dy)
            stride = outstrides[i]
            plane = (<char *>dout[i])[:(height * stride)]
            out.append(plane)
            strides.append(outstrides[i])
        return  0, strides, out

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
        cdef int i = 0                          #@DuplicatedSignature
        assert self.context!=NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        padded_buf = <unsigned char *> xmemalign(buf_len+32)
        if padded_buf==NULL:
            return 100, "", 0
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 32)
        set_decoder_csc_format(self.context, int(options.get("csc_pixel_format", -1)))
        dout = NULL
        with nogil:
            i = decompress_image(self.context, padded_buf, buf_len, &yuvplanes, &yuvstrides)
            xmemfree(padded_buf)
            if i==0:
                i = csc_image_yuv2rgb(self.context, yuvplanes, yuvstrides, &dout, &outsize, &outstride)
        if i!=0:
            if dout!=NULL:
                xmemfree(dout)
            return i, "", 0
        outstr = (<char *>dout)[:outsize]
        xmemfree(dout)
        return  i, outstr, outstride
