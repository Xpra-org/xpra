# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import os
from xpra.codecs.codec_constants import codec_spec

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_VPX_DEBUG")
error = log.error

VPX_THREADS = os.environ.get("XPRA_VPX_THREADS", "2")

DEF ENABLE_VP8 = True
DEF ENABLE_VP9 = False


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

USAGE_STREAM_FROM_SERVER    = 0x0
USAGE_LOCAL_FILE_PLAYBACK   = 0x1
USAGE_CONSTRAINED_QUALITY   = 0x2
USAGE_CONSTANT_QUALITY      = 0x3


cdef extern from "vpx/vpx_codec.h":
    ctypedef const void *vpx_codec_iter_t
    ctypedef long vpx_codec_flags_t
    ctypedef int vpx_codec_err_t
    ctypedef struct vpx_codec_ctx_t:
        pass
    const char *vpx_codec_error(vpx_codec_ctx_t  *ctx)
    vpx_codec_err_t vpx_codec_destroy(vpx_codec_ctx_t *ctx)
    const char *vpx_codec_version_str()

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
    IF ENABLE_VP8 == True:
        const vpx_codec_iface_t *vpx_codec_vp8_cx()
    IF ENABLE_VP9 == True:
        const vpx_codec_iface_t *vpx_codec_vp9_cx()

cdef extern from "vpx/vpx_encoder.h":
    int VPX_ENCODER_ABI_VERSION
    #vpx_rc_mode
    int VPX_VBR         #Variable Bit Rate (VBR) mode
    int VPX_CBR         #Constant Bit Rate (CBR) mode
    int VPX_CQ          #Constant Quality (CQ) mode
    #vpx_enc_pass:
    int VPX_RC_ONE_PASS
    int VPX_RC_FIRST_PASS
    int VPX_RC_LAST_PASS
    #vpx_kf_mode:
    int VPX_KF_FIXED
    int VPX_KF_AUTO
    int VPX_KF_DISABLED
    long VPX_EFLAG_FORCE_KF
    ctypedef struct vpx_rational_t:
        int num     #fraction numerator
        int den     #fraction denominator
    ctypedef struct vpx_codec_enc_cfg_t:
        unsigned int g_usage
        unsigned int g_threads
        unsigned int g_profile
        unsigned int g_w
        unsigned int g_h
        vpx_rational_t g_timebase
        unsigned int g_error_resilient
        unsigned int g_pass
        unsigned int g_lag_in_frames
        unsigned int rc_dropframe_thresh
        unsigned int rc_resize_allowed
        unsigned int rc_resize_up_thresh
        unsigned int rc_resize_down_thresh
        int rc_end_usage
        #struct vpx_fixed_buf rc_twopass_stats_in
        unsigned int rc_target_bitrate
        unsigned int rc_min_quantizer
        unsigned int rc_max_quantizer
        unsigned int rc_undershoot_pct
        unsigned int rc_overshoot_pct
        unsigned int rc_buf_sz
        unsigned int rc_buf_initial_sz
        unsigned int rc_buf_optimal_sz
        #we don't use 2pass:
        #unsigned int rc_2pass_vbr_bias_pct
        #unsigned int rc_2pass_vbr_minsection_pct
        #unsigned int rc_2pass_vbr_maxsection_pct
        unsigned int kf_mode
        unsigned int kf_min_dist
        unsigned int kf_max_dist
        unsigned int ts_number_layers
        unsigned int[5] ts_target_bitrate
        unsigned int[5] ts_rate_decimator
        unsigned int ts_periodicity
        unsigned int[16] ts_layer_id
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
    int get_packet_kind(const vpx_codec_cx_pkt_t *pkt)
    char *get_frame_buffer(const vpx_codec_cx_pkt_t *pkt)
    size_t get_frame_size(const vpx_codec_cx_pkt_t *pkt)


def get_abi_version():
    return VPX_ENCODER_ABI_VERSION

def get_version():
    return vpx_codec_version_str()

def get_type():
    return "vpx"

CODECS = []
IF ENABLE_VP8 == True:
    CODECS.append("vp8")
IF ENABLE_VP9 == True:
    CODECS.append("vp9")

def get_encodings():
    return CODECS


cdef const vpx_codec_iface_t  *make_codec_cx(encoding):
    IF ENABLE_VP8 == True:
        if encoding=="vp8":
            return vpx_codec_vp8_cx()
    IF ENABLE_VP9 == True:
        if encoding=="vp9":
            return vpx_codec_vp9_cx()
    raise Exception("unsupported encoding: %s" % encoding)


#https://groups.google.com/a/webmproject.org/forum/?fromgroups#!msg/webm-discuss/f5Rmi-Cu63k/IXIzwVoXt_wJ
#"RGB is not supported.  You need to convert your source to YUV, and then compress that."
COLORSPACES = ["YUV420P"]
def get_colorspaces():
    return COLORSPACES

def get_spec(encoding, colorspace):
    assert encoding in CODECS, "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES)
    #quality: we only handle YUV420P but this is already accounted for by get_colorspaces() based score calculations
    #setup cost is reasonable (usually about 5ms)
    return codec_spec(Encoder, codec_type=get_type(), encoding=encoding, setup_cost=40)

cdef vpx_img_fmt_t get_vpx_colorspace(colorspace):
    assert colorspace in COLORSPACES
    return VPX_IMG_FMT_I420

def init_module():
    #nothing to do!
    pass


cdef class Encoder:
    cdef int frames
    cdef vpx_codec_ctx_t *context
    cdef vpx_codec_enc_cfg_t *cfg
    cdef vpx_img_fmt_t pixfmt
    cdef int width
    cdef int height
    cdef int max_threads
    cdef object encoding
    cdef char* src_format

    def init_context(self, int width, int height, src_format, encoding, int quality, int speed, scaling, options):    #@DuplicatedSignature
        assert encoding in CODECS, "invalid encoding: %s" % encoding
        assert scaling==(1,1), "vpx does not handle scaling"
        cdef const vpx_codec_iface_t *codec_iface = make_codec_cx(encoding)
        self.encoding = encoding
        self.width = width
        self.height = height
        self.frames = 0
        assert src_format=="YUV420P"
        self.src_format = "YUV420P"
        self.pixfmt = get_vpx_colorspace(self.src_format)
        try:
            self.max_threads = max(0, min(32, int(options.get("threads", VPX_THREADS))))
        except Exception, e:
            log.warn("error parsing number of threads: %s", e)
            self.max_threads =2

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
        self.cfg.g_usage = USAGE_STREAM_FROM_SERVER
        self.cfg.g_threads = self.max_threads
        self.cfg.g_profile = 0                      #use 1 for YUV444P and RGB support
        self.cfg.g_w = width
        self.cfg.g_h = height
        cdef vpx_rational_t timebase
        timebase.num = 1
        timebase.den = 1000
        self.cfg.g_timebase = timebase
        self.cfg.g_error_resilient = 0              #we currently use TCP, guaranteed delivery
        self.cfg.g_pass = VPX_RC_ONE_PASS
        self.cfg.g_lag_in_frames = 0                #always give us compressed output for each frame without delay
        self.cfg.rc_resize_allowed = 1
        self.cfg.rc_end_usage = VPX_VBR
        self.cfg.kf_mode = VPX_KF_AUTO    #VPX_KF_DISABLED
        if vpx_codec_enc_init_ver(self.context, codec_iface, self.cfg, 0, VPX_ENCODER_ABI_VERSION)!=0:
            free(self.context)
            raise Exception("failed to initialized vpx encoder: %s", vpx_codec_error(self.context))
        debug("vpx_codec_enc_init_ver for %s succeeded", encoding)

    def __str__(self):
        return "vpx.Encoder(%s)" % self.encoding

    def get_info(self):
        return {"frames"    : self.frames,
                "width"     : self.width,
                "height"    : self.height,
                "encoding"  : self.encoding,
                "src_format": self.src_format,
                "max_threads": self.max_threads}

    def get_encoding(self):
        return self.encoding

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
        #this is the chroma shift for YUV420P:
        #both X and Y are downscaled by 2^1
        image.x_chroma_shift = 1
        image.y_chroma_shift = 1
        image.bps = 0
        if self.frames==0:
            flags |= VPX_EFLAG_FORCE_KF
        start = time.time()
        with nogil:
            i = vpx_codec_encode(self.context, image, self.frames, 1, flags, VPX_DL_REALTIME)
        if i!=0:
            free(image)
            log.error("%s codec encoding error: %s", self.encoding, vpx_codec_destroy(self.context))
            return None
        end = time.time()
        debug("vpx_codec_encode for %s took %.1f", self.encoding, 1000.0*(end-start))
        with nogil:
            pkt = vpx_codec_get_cx_data(self.context, &iter)
        end = time.time()
        if get_packet_kind(pkt) != VPX_CODEC_CX_FRAME_PKT:
            free(image)
            log.error("%s invalid packet type: %s", self.encoding, get_packet_kind(pkt))
            return None
        self.frames += 1
        #we copy the compressed data here, we could manage the buffer instead
        #using vpx_codec_set_cx_data_buf every time with a wrapper for freeing it,
        #but since this is compressed data, no big deal
        coutsz = get_frame_size(pkt)
        cout = get_frame_buffer(pkt)
        img = cout[:coutsz]
        free(image)
        debug("vpx returning %s image: %s bytes", self.encoding, len(img))
        return img

    def set_encoding_speed(self, int pct):
        return

    def set_encoding_quality(self, int pct):
        return
