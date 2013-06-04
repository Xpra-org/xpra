# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from libc.stdlib cimport free

from xpra.codecs.codec_constants import get_subsampling_divs, get_colorspace_from_avutil_enum, RGB_FORMATS 
from xpra.codecs.image_wrapper import ImageWrapper

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
ctypedef void dec_avcodec_ctx
cdef extern from "dec_avcodec.h":
    dec_avcodec_ctx *init_decoder(int width, int height, const char *colorspace)
    void set_decoder_csc_format(dec_avcodec_ctx *ctx, int csc_fmt)
    void clean_decoder(dec_avcodec_ctx *)
    int decompress_image(dec_avcodec_ctx *ctx, const uint8_t *input_image, int size, uint8_t *out[3], int outstride[3])
    const char *get_colorspace(dec_avcodec_ctx *)


cdef class Decoder:
    cdef dec_avcodec_ctx *context
    cdef int width
    cdef int height

    def init_context(self, width, height, colorspace):
        self.width = width
        self.height = height
        self.context = init_decoder(self.width, self.height, colorspace)
        assert self.context!=NULL, "failed to init decoder for %sx%s %s" % (self.width, self.height, colorspace)

    def get_info(self):
        return {
                "width"     : self.get_width(),
                "height"    : self.get_height(),
                "type"      : self.get_type(),
                "colorspace": self.get_colorspace(),
                }

    def is_closed(self):
        return self.context==NULL

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):
        return "x264"

    def clean(self):
        if self.context!=NULL:
            clean_decoder(self.context)
            self.context = NULL

    def decompress_image(self, input, options):
        cdef uint8_t *dout[3]
        cdef int outstrides[3]
        cdef unsigned char * padded_buf = NULL
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int i = 0
        assert self.context!=NULL
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        i = decompress_image(self.context, buf, buf_len, dout, outstrides)
        if i!=0:
            return None
        out = []
        strides = []
        #print("decompress image: colorspace=%s" % self.get_colorspace())
        if self.get_colorspace() in RGB_FORMATS:
            strides = outstrides[0]+outstrides[1]+outstrides[2]
            out = (<char *>dout[i])[:(self.height * strides)]
            nplanes = 0
        else:
            #if self.get_colorspace() in RGB_FORMATS:
            #    divs = (1, 1), (1, 1), (1, 1)
            #else:
            divs = get_subsampling_divs(self.get_colorspace())
            nplanes = 3
            for i in range(nplanes):
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
                strides.append(stride)
        img = ImageWrapper(0, 0, self.width, self.height, out, self.get_colorspace(), 24, strides, nplanes)
        return  img

    def get_colorspace(self):
        return get_colorspace(self.context)
