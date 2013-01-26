# This file is part of Parti.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from libc.stdlib cimport free

DEFAULT_INITIAL_QUALITY = 70
DEFAULT_INITIAL_SPEED = 20
ALL_PROFILES = ["baseline", "main", "high", "high10", "high422", "high444"]
I420_PROFILES = ALL_PROFILES[:]
I422_PROFILES = ["high422", "high444"]
I444_PROFILES = ["high444"]
DEFAULT_I420_PROFILE = "baseline"
DEFAULT_I422_PROFILE = "high422"
DEFAULT_I444_PROFILE = "high444"
DEFAULT_I422_QUALITY = 70
DEFAULT_I422_MIN_QUALITY = 50
DEFAULT_I444_QUALITY = 90
DEFAULT_I444_MIN_QUALITY = 75

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

    x264lib_ctx* init_encoder(int width, int height,
                              int initial_quality, int initial_speed,
                              int supports_csc_option,
                              int I422_quality, int I444_quality,
                              int I422_min, int I444_min,
                              char *i420_profile, char *i422_profile, char *i444_profile)
    void clean_encoder(x264lib_ctx *context)
    x264_picture_t* csc_image_rgb2yuv(x264lib_ctx *ctx, uint8_t *input, int stride)
    int compress_image(x264lib_ctx *ctx, x264_picture_t *pic_in, uint8_t **out, int *outsz) nogil
    int get_encoder_pixel_format(x264lib_ctx *ctx)
    int get_encoder_quality(x264lib_ctx *ctx)
    int get_encoder_speed(x264lib_ctx *ctx)
    int get_pixel_format(int csc_format)

    x264lib_ctx* init_decoder(int width, int height, int csc_fmt)
    void set_decoder_csc_format(x264lib_ctx *context, int csc_fmt)
    void clean_decoder(x264lib_ctx *context)
    int decompress_image(x264lib_ctx *context, uint8_t *input, int size, uint8_t *(*out)[3], int (*outstride)[3]) nogil
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
            i = decompress_image(self.context, buf, buf_len, &dout, &outstrides)
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
            i = decompress_image(self.context, padded_buf, buf_len, &yuvplanes, &yuvstrides)
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

    def _get_profile(self, options, csc_mode, default_value, valid_options):
        #try the environment as a default, fallback to hardcoded default:
        profile = os.environ.get("XPRA_X264_%s_PROFILE" % csc_mode, default_value)
        #now see if the client has requested a different value:
        profile = options.get("x264.%s.profile" % csc_mode, profile)
        if profile not in valid_options:
            print("invalid %s profile: %s" % (csc_mode, profile))
            return default_value
        return profile

    def _get_min_quality(self, options, csc_mode, default_value):
        #try the environment as a default, fallback to hardcoded default:
        min_quality = int(os.environ.get("XPRA_X264_%s_MIN_QUALITY" % csc_mode, default_value))
        #now see if the client has requested a different value:
        min_quality = options.get("x264.%s.min_quality" % csc_mode, min_quality)
        #enforce valid range:
        return min(100, max(-1, min_quality))

    def _get_quality(self, options, csc_mode, default_value):
        #try the environment as a default, fallback to hardcoded default:
        quality = int(os.environ.get("XPRA_X264_%s_QUALITY" % csc_mode, default_value))
        #now see if the client has requested a different value:
        quality = options.get("x264.%s.quality" % csc_mode, quality)
        #enforce valid range:
        return min(100, max(-1, quality))

    def init_context(self, int width, int height, options):    #@DuplicatedSignature
        self.init(width, height)
        self.frames = 0
        self.supports_options = int(options.get("encoding_client_options", False))
        I420_profile = self._get_profile(options, "I420", DEFAULT_I420_PROFILE, I420_PROFILES)
        I422_profile = self._get_profile(options, "I422", DEFAULT_I422_PROFILE, I422_PROFILES)
        I444_profile = self._get_profile(options, "I444", DEFAULT_I444_PROFILE, I444_PROFILES)
        I422_quality = self._get_quality(options, "I422", DEFAULT_I422_QUALITY)
        I444_quality = self._get_quality(options, "I444", DEFAULT_I444_QUALITY)
        I422_min = self._get_min_quality(options, "I422", DEFAULT_I422_MIN_QUALITY)
        I444_min = self._get_min_quality(options, "I444", DEFAULT_I444_MIN_QUALITY)
        initial_quality = options.get("initial_quality", options.get("quality", DEFAULT_INITIAL_QUALITY))
        initial_speed = options.get("initial_speed", options.get("speed", DEFAULT_INITIAL_SPEED))
        initial_quality = min(100, max(0, initial_quality))
        initial_speed = min(100, max(0, initial_speed))
        self.context = init_encoder(width, height,
                                    initial_quality, initial_speed,
                                    int(self.supports_options),
                                    int(I422_quality), int(I444_quality),
                                    int(I422_min), int(I444_min),
                                    I420_profile, I422_profile, I444_profile)

    def clean(self):                        #@DuplicatedSignature
        if self.context!=NULL:
            clean_encoder(self.context)
            self.context = NULL

    def get_client_options(self, options):
        csc_pf = get_encoder_pixel_format(self.context)
        client_options = {
                "csc_pixel_format" : csc_pf,
                "pixel_format" : get_pixel_format(csc_pf),
                "frame" : self.frames
                }
        q = client_options.get("quality", -1)
        if q<0:
            q = get_encoder_quality(self.context)
        client_options["quality"] = q
        s = client_options.get("speed", -1)
        if s<0:
            s = get_encoder_speed(self.context)
        client_options["speed"] = s
        return  client_options

    def compress_image(self, input, rowstride, options):
        cdef x264_picture_t *pic_in = NULL
        cdef uint8_t *pic_buf = NULL
        cdef Py_ssize_t pic_buf_len = 0
        cdef int quality_override = options.get("quality", -1)
        cdef int speed_override = options.get("speed", -1)
        cdef int saved_quality = get_encoder_quality(self.context)
        cdef int saved_speed = get_encoder_speed(self.context)
        if speed_override>=0 and saved_speed!=speed_override:
            set_encoding_speed(self.context, speed_override)
        if quality_override>=0 and saved_quality!=quality_override:
            set_encoding_quality(self.context, quality_override)
        assert self.context!=NULL
        #colourspace conversion with gil held:
        PyObject_AsReadBuffer(input, <const_void_pp> &pic_buf, &pic_buf_len)
        pic_in = csc_image_rgb2yuv(self.context, pic_buf, rowstride)
        assert pic_in!=NULL, "colourspace conversion failed"
        try:
            return self.do_compress_image(pic_in), self.get_client_options(options)
        finally:
            if speed_override>=0 and saved_speed!=speed_override:
                set_encoding_speed(self.context, saved_speed)
            if quality_override>=0 and saved_quality!=quality_override:
                set_encoding_quality(self.context, saved_quality)

    cdef do_compress_image(self, x264_picture_t *pic_in):
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
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        assert self.context!=NULL, "context is closed!"
        set_encoding_speed(self.context, pct)

    def set_encoding_quality(self, int pct):
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        assert self.context!=NULL, "context is closed!"
        set_encoding_quality(self.context, pct)
