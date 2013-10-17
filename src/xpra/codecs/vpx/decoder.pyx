# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.codecs.codec_constants import codec_spec, get_subsampling_divs
from xpra.codecs.image_wrapper import ImageWrapper

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_VPX_DEBUG")
error = log.error

from libc.stdint cimport int64_t


cdef extern from "string.h":
    void * memset(void * ptr, int value, size_t num) nogil
    void free(void * ptr) nogil

cdef extern from "../memalign/memalign.h":
    void *xmemalign(size_t size)

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

ctypedef unsigned char uint8_t
ctypedef long vpx_img_fmt_t
ctypedef void vpx_codec_iface_t

cdef extern from "vpx/vpx_codec.h":
    ctypedef const void *vpx_codec_iter_t
    ctypedef long vpx_codec_flags_t
    ctypedef int vpx_codec_err_t
    ctypedef struct vpx_codec_ctx_t:
        pass
    const char *vpx_codec_error(vpx_codec_ctx_t  *ctx)
    vpx_codec_err_t vpx_codec_destroy(vpx_codec_ctx_t *ctx)

cdef extern from "vpx/vpx_image.h":
    cdef int VPX_IMG_FMT_I420
    ctypedef struct vpx_image_t:
        unsigned int w
        unsigned int h
        unsigned int d_w
        unsigned int d_h
        vpx_img_fmt_t fmt
        unsigned char *planes[4]
        int stride[4]
        int bps
        unsigned int x_chroma_shift
        unsigned int y_chroma_shift

cdef extern from "vpx/vp8dx.h":
    vpx_codec_iface_t *vpx_codec_vp8_dx()

cdef extern from "vpx/vpx_decoder.h":
    ctypedef struct vpx_codec_enc_cfg_t:
        unsigned int rc_target_bitrate
        unsigned int g_lag_in_frames
        unsigned int rc_dropframe_thresh
        unsigned int rc_resize_allowed
        unsigned int g_w
        unsigned int g_h
        unsigned int g_error_resilient
    ctypedef struct vpx_codec_dec_cfg_t:
        pass
    cdef int VPX_CODEC_OK
    cdef int VPX_DECODER_ABI_VERSION

    vpx_codec_err_t vpx_codec_dec_init_ver(vpx_codec_ctx_t *ctx, vpx_codec_iface_t *iface,
                                            vpx_codec_dec_cfg_t *cfg, vpx_codec_flags_t flags, int ver)

    vpx_codec_err_t vpx_codec_decode(vpx_codec_ctx_t *ctx, const uint8_t *data,
                                     unsigned int data_sz, void *user_priv, long deadline)

    vpx_image_t *vpx_codec_get_frame(vpx_codec_ctx_t *ctx, vpx_codec_iter_t *iter)



cdef extern from "vpxlib.h":
    int get_vpx_abi_version()


def get_version():
    return get_vpx_abi_version()

def get_type(self):
    return  "vpx"


#https://groups.google.com/a/webmproject.org/forum/?fromgroups#!msg/webm-discuss/f5Rmi-Cu63k/IXIzwVoXt_wJ
#"RGB is not supported.  You need to convert your source to YUV, and then compress that."
COLORSPACES = ["YUV420P"]
def get_colorspaces():
    return COLORSPACES

def get_spec(colorspace):
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES)
    #ratings: quality, speed, setup cost, cpu cost, gpu cost, latency, max_w, max_h, max_pixels
    #quality: we only handle YUV420P but this is already accounted for by get_colorspaces() based score calculations
    #setup cost is reasonable (usually about 5ms)
    return codec_spec(Decoder, codec_type="vpx", setup_cost=40)

cdef vpx_img_fmt_t get_vpx_colorspace(colorspace):
    assert colorspace in COLORSPACES
    return VPX_IMG_FMT_I420


cdef class Decoder:

    cdef vpx_codec_ctx_t *context
    cdef int width
    cdef int height
    cdef vpx_img_fmt_t pixfmt
    cdef char* src_format

    def init_context(self, encoding, width, height, colorspace):
        cdef const vpx_codec_iface_t *codec_iface = vpx_codec_vp8_dx()
        cdef int flags = 0
        assert encoding=="vpx"
        assert colorspace=="YUV420P"
        self.src_format = "YUV420P"
        self.pixfmt = get_vpx_colorspace(self.src_format)
        self.width = width
        self.height = height
        self.context = <vpx_codec_ctx_t *> xmemalign(sizeof(vpx_codec_ctx_t))
        assert self.context!=NULL
        memset(self.context, 0, sizeof(vpx_codec_ctx_t))
        if vpx_codec_dec_init_ver(self.context, codec_iface, NULL,
                              flags, VPX_DECODER_ABI_VERSION)!=VPX_CODEC_OK:
            raise Exception("failed to instantiate vpx decoder: %s" % vpx_codec_error(self.context))

    def get_info(self):
        return {"type"      : self.get_type(),
                "width"     : self.get_width(),
                "height"    : self.get_height(),
                "colorspace": self.get_colorspace(),
                }

    def get_colorspace(self):
        return self.src_format

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def is_closed(self):
        return self.context==NULL

    def get_type(self):                 #@DuplicatedSignature
        return  "vpx"

    def __dealloc__(self):
        self.clean()

    def clean(self):
        if self.context!=NULL:
            vpx_codec_destroy(self.context)
            self.context = NULL

    def decompress_image(self, input, options):
        cdef vpx_image_t *img
        cdef vpx_codec_iter_t iter = NULL
        cdef const uint8_t *frame = input
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int i = 0
        assert self.context!=NULL
        assert PyObject_AsReadBuffer(input, <const void**> &buf, &buf_len)==0

        if vpx_codec_decode(self.context, buf, buf_len, NULL, 0)!=VPX_CODEC_OK:
            log.warn("error during vpx_codec_decode: %s" % vpx_codec_error(self.context))
            return None
        img = vpx_codec_get_frame(self.context, &iter)
        if img==NULL:
            log.warn("error during vpx_codec_get_frame: %s" % vpx_codec_error(self.context))
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
            stride = img.stride[i]
            plane = (<char *>img.planes[i])[:(height * stride)]
            out.append(plane)
            strides.append(stride)
        image = ImageWrapper(0, 0, self.width, self.height, out, self.get_colorspace(), 24, strides, 3)
        return image
