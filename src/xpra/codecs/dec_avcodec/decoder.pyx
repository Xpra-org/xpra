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
    object PyBuffer_FromMemory(void *ptr, Py_ssize_t size)
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

ctypedef unsigned char uint8_t
ctypedef void dec_avcodec_ctx
cdef extern from "dec_avcodec.h":
    char *get_avcodec_version()

    char **get_supported_colorspaces()

    dec_avcodec_ctx *init_decoder(int width, int height, const char *colorspace)
    void set_decoder_csc_format(dec_avcodec_ctx *ctx, int csc_fmt)
    void clean_decoder(dec_avcodec_ctx *)
    int decompress_image(dec_avcodec_ctx *ctx, const uint8_t *input_image, int size, uint8_t *out[3], int outstride[3]) nogil
    const char *get_colorspace(dec_avcodec_ctx *)
    const char *get_actual_colorspace(dec_avcodec_ctx *)


def get_version():
    return get_avcodec_version()

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


cdef class Decoder:
    cdef dec_avcodec_ctx *context
    cdef int width
    cdef int height
    cdef char *colorspace
    cdef object last_image

    def init_context(self, width, height, colorspace):
        self.width = width
        self.height = height
        assert colorspace in COLORSPACES, "invalid colorspace: %s" % colorspace
        for x in COLORSPACES:
            if x==colorspace:
                self.colorspace = x
                break
        self.context = init_decoder(self.width, self.height, self.colorspace)
        assert self.context!=NULL, "failed to init decoder for %sx%s %s" % (self.width, self.height, colorspace)
        self.last_image = None

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
        if self.last_image:
            #make sure the ImageWrapper does not reference memory
            #that is going to be freed!
            self.last_image.clone_pixel_data()
            self.last_image = None
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
        if self.last_image:
            #if another thread is still using this image
            #it is probably too late to prevent a race...
            #(it may be using the buffer directly by now)
            #but at least try to prevent new threads from
            #using the same buffer we are about to write to:
            self.last_image.clone_pixel_data()
            self.last_image = None
        PyObject_AsReadBuffer(input, <const_void_pp> &buf, &buf_len)
        with nogil:
            i = decompress_image(self.context, buf, buf_len, dout, outstrides)
        if i!=0:
            return None
        out = []
        strides = []
        #print("decompress image: colorspace=%s / %s" % (self.colorspace, self.get_colorspace()))
        cs = self.get_actual_colorspace()
        if cs.endswith("P"):
            divs = get_subsampling_divs(cs)
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
                plane = PyBuffer_FromMemory(<void *>dout[i], height * stride)
                out.append(plane)
                strides.append(stride)
        else:
            strides = outstrides[0]+outstrides[1]+outstrides[2]
            out = PyBuffer_FromMemory(<void *>dout[0], self.height * strides)
            nplanes = 0
        img = ImageWrapper(0, 0, self.width, self.height, out, cs, 24, strides, nplanes)
        self.last_image = img
        return img

    def get_colorspace(self):
        return self.colorspace

    def get_actual_colorspace(self):
        return get_colorspace(self.context)
