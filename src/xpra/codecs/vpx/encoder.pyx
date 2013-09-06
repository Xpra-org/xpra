# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.codecs.codec_constants import codec_spec

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

cdef extern from "vpx/vp8cx.h":
    const vpx_codec_iface_t  *vpx_codec_vp8_cx()

cdef extern from "vpx/vpx_encoder.h":
    ctypedef struct vpx_codec_enc_cfg_t:
        unsigned int rc_target_bitrate
        unsigned int g_lag_in_frames
        unsigned int rc_dropframe_thresh
        unsigned int rc_resize_allowed
        unsigned int g_w
        unsigned int g_h
        unsigned int g_error_resilient
    ctypedef int vpx_codec_cx_pkt_kind
    ctypedef int64_t vpx_codec_pts_t
    ctypedef long vpx_enc_frame_flags_t
    ctypedef struct vpx_codec_cx_pkt_t:
        pass
    cdef int VPX_DL_REALTIME
    cdef vpx_codec_cx_pkt_kind VPX_CODEC_CX_FRAME_PKT
    vpx_codec_err_t vpx_codec_enc_config_default(vpx_codec_iface_t *iface,
                              vpx_codec_enc_cfg_t *cfg, unsigned int usage)
    vpx_codec_err_t vpx_codec_enc_init_ver(vpx_codec_ctx_t *ctx, vpx_codec_iface_t *iface,
                                       vpx_codec_enc_cfg_t  *cfg, vpx_codec_flags_t flags, int abi_version)

    vpx_codec_err_t vpx_codec_encode(vpx_codec_ctx_t *ctx, const vpx_image_t *img,
                              vpx_codec_pts_t pts, unsigned long duration,
                              vpx_enc_frame_flags_t flags, unsigned long deadline) nogil

    const vpx_codec_cx_pkt_t *vpx_codec_get_cx_data(vpx_codec_ctx_t *ctx, vpx_codec_iter_t *iter) nogil


cdef extern from "vpxlib.h":
    int get_vpx_abi_version()

    int get_packet_kind(const vpx_codec_cx_pkt_t *pkt)
    char *get_frame_buffer(const vpx_codec_cx_pkt_t *pkt)
    size_t get_frame_size(const vpx_codec_cx_pkt_t *pkt)


def get_version():
    return get_vpx_abi_version()

def get_type():
    return "vpx"


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
    return codec_spec(Encoder, codec_class="vpx", setup_cost=40)

cdef vpx_img_fmt_t get_vpx_colorspace(colorspace):
    assert colorspace in COLORSPACES
    return VPX_IMG_FMT_I420


cdef class Encoder:
    cdef int frames
    cdef vpx_codec_ctx_t *context
    cdef vpx_codec_enc_cfg_t *cfg
    cdef vpx_img_fmt_t pixfmt
    cdef int width
    cdef int height
    cdef char* src_format

    def init_context(self, int width, int height, src_format, int quality, int speed, options):    #@DuplicatedSignature
        cdef const vpx_codec_iface_t *codec_iface
        self.width = width
        self.height = height
        self.frames = 0
        assert src_format=="YUV420P"
        self.src_format = "YUV420P"
        self.pixfmt = get_vpx_colorspace(self.src_format)

        codec_iface = vpx_codec_vp8_cx()
        self.cfg = <vpx_codec_enc_cfg_t *> xmemalign(sizeof(vpx_codec_enc_cfg_t))
        if self.cfg==NULL:
            raise Exception("failed to allocate memory for vpx encoder config")
        if vpx_codec_enc_config_default(codec_iface, self.cfg, 0)!=0:
            free(self.cfg)
            raise Exception("failed to create vpx encoder config")

        self.context = <vpx_codec_ctx_t *> xmemalign(sizeof(vpx_codec_ctx_t))
        if self.context==NULL:
            free(self.cfg)
            raise Exception("failed to allocate memory for vpx encoder context")
        memset(self.context, 0, sizeof(vpx_codec_ctx_t))

        self.cfg.rc_target_bitrate = width * height * self.cfg.rc_target_bitrate / self.cfg.g_w / self.cfg.g_h
        self.cfg.g_w = width
        self.cfg.g_h = height
        self.cfg.g_error_resilient = 0
        self.cfg.g_lag_in_frames = 0
        self.cfg.rc_dropframe_thresh = 0
        self.cfg.rc_resize_allowed = 1
        if vpx_codec_enc_init_ver(self.context, codec_iface, self.cfg, 0, get_vpx_abi_version())!=0:
            free(self.context)
            raise Exception("failed to initialized vpx encoder: %s", vpx_codec_error(self.context))


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

    def get_type(self):                     #@DuplicatedSignature
        return  "vpx"

    def get_src_format(self):
        return self.src_format

    def __dealloc__(self):
        self.clean()

    def clean(self):                        #@DuplicatedSignature
        if self.context!=NULL:
            vpx_codec_destroy(self.context)
            free(self.context)
            self.context = NULL
        if self.cfg:
            free(self.cfg)
            self.cfg = NULL

    def compress_image(self, image, options):
        cdef uint8_t *pic_in[3]
        cdef int strides[3]
        cdef uint8_t *pic_buf = NULL
        cdef Py_ssize_t pic_buf_len = 0
        assert self.context!=NULL
        pixels = image.get_pixels()
        istrides = image.get_rowstride()
        assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
        assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
        for i in range(3):
            PyObject_AsReadBuffer(pixels[i], <const void**> &pic_buf, &pic_buf_len)
            pic_in[i] = pic_buf
            strides[i] = istrides[i]
        return self.do_compress_image(pic_in, strides), {"frame" : self.frames}

    cdef do_compress_image(self, uint8_t *pic_in[3], int strides[3]):
        #actual compression (no gil):
        cdef vpx_image_t *image
        cdef const vpx_codec_cx_pkt_t *pkt
        cdef vpx_codec_iter_t iter = NULL
        cdef int frame_cnt = 0
        cdef int flags = 0
        cdef int i                          #@DuplicatedSignature
        cdef char *cout
        cdef unsigned int coutsz
        image = <vpx_image_t *> xmemalign(sizeof(vpx_image_t))
        memset(image, 0, sizeof(vpx_image_t))
        image.w = self.width
        image.h = self.height
        image.fmt = self.pixfmt
        for i in xrange(3):
            image.planes[i] = pic_in[i]
            image.stride[i] = strides[i]
        image.planes[3] = NULL
        image.stride[3] = 0
        image.d_w = self.width
        image.d_h = self.height
        image.x_chroma_shift = 0
        image.y_chroma_shift = 0
        image.bps = 8
        with nogil:
            i = vpx_codec_encode(self.context, image, frame_cnt, 1, flags, VPX_DL_REALTIME)
        if i!=0:
            free(image)
            log.error("vpx codec encoding error: %s", vpx_codec_destroy(self.context))
            return None
        with nogil:
            pkt = vpx_codec_get_cx_data(self.context, &iter)
        if get_packet_kind(pkt) != VPX_CODEC_CX_FRAME_PKT:
            free(image)
            log.error("vpx: invalid packet type: %s", get_packet_kind(pkt))
            return None
        self.frames += 1
        #FIXME: we copy the pixels here, we could manage the buffer instead
        coutsz = get_frame_size(pkt)
        cout = get_frame_buffer(pkt)
        img = cout[:coutsz]
        free(image)
        return img

    def set_encoding_speed(self, int pct):
        return

    def set_encoding_quality(self, int pct):
        return
