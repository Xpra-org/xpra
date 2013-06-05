# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.codecs.codec_constants import codec_spec

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    ctypedef void** const_void_pp "const void**"
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

ctypedef unsigned char uint8_t
ctypedef void vpx_codec_ctx_t
ctypedef void vpx_image_t
cdef extern from "vpxlib.h":
    char **get_supported_colorspaces()

    int get_vpx_abi_version()

    vpx_codec_ctx_t* init_encoder(int width, int height, const char *colorspace)
    void clean_encoder(vpx_codec_ctx_t *context)
    int compress_image(vpx_codec_ctx_t *ctx, uint8_t *input[3], int input_stride[3], uint8_t **out, int *outsz) nogil

    vpx_codec_ctx_t* init_decoder(int width, int height, const char *colorspace)
    void clean_decoder(vpx_codec_ctx_t *context)
    int decompress_image(vpx_codec_ctx_t *context, uint8_t *input, int size, uint8_t *out[3], int outstride[3])


def get_version():
    return get_vpx_abi_version()

#copy C list of colorspaces to a python list:
cdef do_get_colorspaces():
    cdef const char** c_colorspaces
    cdef int i
    c_colorspaces = get_supported_colorspaces()
    i = 0;
    colorspaces = []
    while c_colorspaces[i]!=NULL:
        colorspaces.append(c_colorspaces[i])
        i += 1
    return colorspaces
COLORSPACES = do_get_colorspaces()
def get_colorspaces():
    return COLORSPACES

def get_spec(colorspace):
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES)
    #ratings: quality, speed, setup cost, cpu cost, gpu cost, latency, max_w, max_h, max_pixels
    #quality: we only handle YUV420P but this is already accounted for by get_colorspaces() based score calculations
    #setup cost is reasonable (usually about 5ms)
    return codec_spec(Encoder, setup_cost=40)


cdef class Encoder:
    cdef int frames
    cdef vpx_codec_ctx_t *context
    cdef int width
    cdef int height
    cdef char* src_format

    def init_context(self, int width, int height, src_format, int quality, int speed, options):    #@DuplicatedSignature
        self.width = width
        self.height = height
        self.frames = 0
        #ugly trick to use a string which won't go away from underneath us:
        assert src_format in COLORSPACES
        for x in COLORSPACES:
            if x==src_format:
                self.src_format = x
                break
        self.context = init_encoder(width, height, self.src_format)

    def get_info(self):
        return {"frames"    : self.frames,
                "width"     : self.width,
                "height"    : self.height,
                "src_format": self.src_format}

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def is_closed(self):
        return self.context==NULL

    def get_type(self):
        return  "vpx"

    def get_src_format(self):
        return self.src_format

    def __dealloc__(self):
        self.clean()

    def clean(self):                        #@DuplicatedSignature
        if self.context!=NULL:
            clean_encoder(self.context)
            self.context = NULL

    def compress_image(self, image, options):
        cdef uint8_t *pic_in[3]
        cdef int strides[3]
        cdef uint8_t *pic_buf = NULL
        cdef Py_ssize_t pic_buf_len = 0
        assert self.context!=NULL
        pixels = image.get_pixels()
        istrides = image.get_rowstride()
        if self.src_format.find("RGB")>=0 or self.src_format.find("BGR")>=0:
            assert len(pixels)>0
            assert istrides>0
            PyObject_AsReadBuffer(pixels, <const_void_pp> &pic_buf, &pic_buf_len)
            for i in range(3):
                pic_in[i] = pic_buf
                strides[i] = istrides
        else:
            assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
            assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
            for i in range(3):
                PyObject_AsReadBuffer(pixels[i], <const_void_pp> &pic_buf, &pic_buf_len)
                pic_in[i] = pic_buf
                strides[i] = istrides[i]
        return self.do_compress_image(pic_in, strides), {"frame" : self.frames}

    cdef do_compress_image(self, uint8_t *pic_in[], int strides[]):
        #actual compression (no gil):
        cdef int i                          #@DuplicatedSignature
        cdef uint8_t *cout
        cdef int coutsz
        with nogil:
            i = compress_image(self.context, pic_in, strides, &cout, &coutsz)
        if i!=0:
            return None
        coutv = (<char *>cout)[:coutsz]
        self.frames += 1
        return  coutv

    def set_encoding_speed(self, int pct):
        return

    def set_encoding_quality(self, int pct):
        return
