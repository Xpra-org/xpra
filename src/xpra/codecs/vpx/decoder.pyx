# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from libc.stdlib cimport free

from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.codecs.image_wrapper import ImageWrapper

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    ctypedef void** const_void_pp "const void**"
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

ctypedef unsigned char uint8_t
ctypedef void vpx_codec_ctx_t
ctypedef void vpx_image_t
cdef extern from "vpxlib.h":
    void xmemfree(void* ptr)

    int get_vpx_abi_version()

    vpx_codec_ctx_t* init_decoder(int width, int height, const char *colorspace)
    void clean_decoder(vpx_codec_ctx_t *context)
    int decompress_image(vpx_codec_ctx_t *context, uint8_t *input, int size, uint8_t *out[3], int outstride[3])
    const char *get_colorspace(vpx_codec_ctx_t *context)


def get_version():
    return get_vpx_abi_version()


cdef class Decoder:

    cdef vpx_codec_ctx_t *context
    cdef int width
    cdef int height

    def init_context(self, width, height, colorspace):
        assert colorspace=="YUV420P"
        self.width = width
        self.height = height
        self.context = init_decoder(width, height, colorspace)

    def get_info(self):
        return {"type"      : self.get_type(),
                "width"     : self.get_width(),
                "height"    : self.get_height(),
                "colorspace": self.get_colorspace(),
                }

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def is_closed(self):
        return self.context==NULL

    def get_type(self):
        return  "vpx"

    def __dealloc__(self):
        self.clean()

    def clean(self):
        if self.context!=NULL:
            clean_decoder(self.context)
            self.context = NULL

    def decompress_image(self, input, options):
        cdef uint8_t *dout[3]
        cdef int outstrides[3]
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int i = 0
        assert self.context!=NULL
        assert PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)==0
        i = decompress_image(self.context, buf, buf_len, dout, outstrides)
        if i!=0:
            return None
        out = []
        strides = []
        divs = get_subsampling_divs(self.get_colorspace())
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
        img = ImageWrapper(0, 0, self.width, self.height, out, self.get_colorspace(), 24, strides, 3)
        return img

    def get_colorspace(self):
        return get_colorspace(self.context)

    def get_actual_colorspace(self):
        return get_colorspace(self.context)
