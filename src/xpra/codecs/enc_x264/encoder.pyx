# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import os

from xpra.codecs.codec_constants import get_subsampling_divs, RGB_FORMATS, codec_spec
from xpra.codecs.csc_swscale.colorspace_converter import ColorspaceConverter

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
ctypedef void enc_x264_ctx
cdef extern from "enc_x264.h":
    char **get_supported_colorspaces()

    int get_x264_build_no()

    char * get_profile(enc_x264_ctx *ctx)
    char * get_preset(enc_x264_ctx *ctx)

    enc_x264_ctx *init_encoder(int width, int height,
        const char *colorspace, const char *profile,
        int initial_quality, int initial_speed)
    void clean_encoder(enc_x264_ctx *)
    int compress_image(enc_x264_ctx *ctx, uint8_t *input[3], int in_stride[3], uint8_t **out, int *outsz) nogil
    int get_encoder_quality(enc_x264_ctx *ctx)
    int get_encoder_speed(enc_x264_ctx *ctx)

    void set_encoding_speed(enc_x264_ctx *context, int pct)
    void set_encoding_quality(enc_x264_ctx *context, int pct)


def get_version():
    return get_x264_build_no()

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
    #we can handle high quality and any speed
    #setup cost is moderate (about 10ms)
    return codec_spec(Encoder, 100, 100, 70, 100, 0, 40, 4096, 4096, 4096*4096)


cdef class Encoder:
    cdef int frames
    cdef enc_x264_ctx *context
    cdef int width
    cdef int height
    cdef char *src_format
    cdef double time

    def init_context(self, int width, int height, src_format, int quality, int speed, options):    #@DuplicatedSignature
        self.width = width
        self.height = height
        self.frames = 0
        self.time = 0
        assert src_format in COLORSPACES, "invalid source format: %s" % src_format
        for x in COLORSPACES:
            if x==src_format:
                self.src_format = x
                break
        profile = self._get_profile(options, src_format)
        self.context = init_encoder(self.width, self.height,
                                    self.src_format, profile,
                                    quality, speed)
        if self.context==NULL:
            raise Exception("context initialization failed for format %s" % src_format)

    def get_info(self):
        cdef float pps
        info = {"profile"   : get_profile(self.context),
                "preset"    : get_preset(self.context),
                "frames"    : self.frames,
                "width"     : self.width,
                "height"    : self.height,
                "src_format": self.src_format}
        if self.frames>0 and self.time>0:
            pps = float(self.width) * float(self.height) * float(self.frames) / self.time
            info["total_time_ms"] = int(self.time*1000.0)
            info["pixels_per_second"] = int(pps)
        return info

    def __str__(self):
        return "x264_encoder(%s - %sx%s)" % (self.src_format, self.width, self.height)

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

    def get_src_format(self):
        return self.src_format

    def _get_profile(self, options, csc_mode):
        #try the environment as a default, fallback to hardcoded default:
        profile = os.environ.get("XPRA_X264_%s_PROFILE" % csc_mode, "")
        #now see if the client has requested a different value:
        profile = options.get("x264.%s.profile" % csc_mode, profile)
        return profile

    def clean(self):                        #@DuplicatedSignature
        if self.context!=NULL:
            clean_encoder(self.context)
            self.context = NULL

    def get_client_options(self, options):
        q = options.get("quality", -1)
        if q<0:
            q = get_encoder_quality(self.context)
        s = options.get("speed", -1)
        if s<0:
            s = get_encoder_speed(self.context)
        return {
                "frame"     : self.frames,
                "quality"   : q,
                "speed"     : s,
                }

    def compress_image(self, image, options):
        cdef uint8_t *pic_in[3]
        cdef int strides[3]
        cdef uint8_t *pic_buf
        cdef Py_ssize_t pic_buf_len = 0
        cdef uint8_t *cout
        cdef int coutsz
        cdef int quality_override = options.get("quality", -1)
        cdef int speed_override = options.get("speed", -1)
        cdef int saved_quality = get_encoder_quality(self.context)
        cdef int saved_speed = get_encoder_speed(self.context)
        cdef int i                        #@DuplicatedSignature
        if speed_override>=0 and saved_speed!=speed_override:
            set_encoding_speed(self.context, speed_override)
        if quality_override>=0 and saved_quality!=quality_override:
            set_encoding_quality(self.context, quality_override)
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
        try:
            start = time.time()
            with nogil:
                i = compress_image(self.context, pic_in, strides, &cout, &coutsz)
            if i!=0:
                return None, {}
            coutv = (<char *>cout)[:coutsz]
            end = time.time()
            self.time += end-start
            self.frames += 1
            return  coutv, self.get_client_options(options)
        finally:
            if speed_override>=0 and saved_speed!=speed_override:
                set_encoding_speed(self.context, saved_speed)
            if quality_override>=0 and saved_quality!=quality_override:
                set_encoding_quality(self.context, saved_quality)


    def set_encoding_speed(self, int pct):
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        assert self.context!=NULL, "context is closed!"
        set_encoding_speed(self.context, pct)

    def set_encoding_quality(self, int pct):
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        assert self.context!=NULL, "context is closed!"
        set_encoding_quality(self.context, pct)
