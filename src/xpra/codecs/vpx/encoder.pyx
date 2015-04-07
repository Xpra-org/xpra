# This file is part of Xpra.
# Copyright (C) 2012-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import os
from xpra.codecs.codec_constants import video_codec_spec

from xpra.log import Logger
log = Logger("encoder", "vpx")


#sensible default:
cpus = 2
try:
    cpus = os.cpu_count()
except:
    try:
        import multiprocessing
        cpus = multiprocessing.cpu_count()
    except:
        pass
VPX_THREADS = os.environ.get("XPRA_VPX_THREADS", max(1, cpus-1))

DEF ENABLE_VP8 = True
DEF ENABLE_VP9 = True
DEF ENABLE_VP9_YUV444 = True


from libc.stdint cimport int64_t

cdef extern from "string.h":
    void *memset(void *ptr, int value, size_t num) nogil
    void free(void *ptr) nogil


cdef extern from "../buffers/memalign.h":
    void *xmemalign(size_t size)

cdef extern from "../buffers/buffers.h":
    int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)

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
    const char *vpx_codec_err_to_string(vpx_codec_err_t err)
    const char *vpx_codec_error(vpx_codec_ctx_t  *ctx)
    vpx_codec_err_t vpx_codec_destroy(vpx_codec_ctx_t *ctx)
    const char *vpx_codec_version_str()
    const char *vpx_codec_build_config()

cdef extern from "vpx/vpx_image.h":
    cdef int VPX_IMG_FMT_I420
    cdef int VPX_IMG_FMT_I444
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
    ctypedef int64_t vpx_codec_pts_t
    ctypedef long vpx_enc_frame_flags_t

    cdef int VPX_CODEC_CX_FRAME_PKT
    cdef int VPX_CODEC_STATS_PKT
    cdef int VPX_CODEC_PSNR_PKT
    cdef int VPX_CODEC_CUSTOM_PKT

    ctypedef struct frame:
        void    *buf
        size_t  sz

    ctypedef struct data:
        frame frame

    ctypedef struct vpx_codec_cx_pkt_t:
        int kind
        data data

    cdef int VPX_DL_REALTIME
    cdef int VPX_DL_GOOD_QUALITY
    cdef int VPX_DL_BEST_QUALITY

    vpx_codec_err_t vpx_codec_enc_config_default(vpx_codec_iface_t *iface,
                              vpx_codec_enc_cfg_t *cfg, unsigned int usage)
    vpx_codec_err_t vpx_codec_enc_init_ver(vpx_codec_ctx_t *ctx, vpx_codec_iface_t *iface,
                                       vpx_codec_enc_cfg_t  *cfg, vpx_codec_flags_t flags, int abi_version)

    vpx_codec_err_t vpx_codec_encode(vpx_codec_ctx_t *ctx, const vpx_image_t *img,
                              vpx_codec_pts_t pts, unsigned long duration,
                              vpx_enc_frame_flags_t flags, unsigned long deadline) nogil

    const vpx_codec_cx_pkt_t *vpx_codec_get_cx_data(vpx_codec_ctx_t *ctx, vpx_codec_iter_t *iter) nogil
    vpx_codec_err_t vpx_codec_enc_config_set(vpx_codec_ctx_t *ctx, const vpx_codec_enc_cfg_t *cfg)

PACKET_KIND = {
               VPX_CODEC_CX_FRAME_PKT   : "CX_FRAME_PKT",
               VPX_CODEC_STATS_PKT      : "STATS_PKT",
               VPX_CODEC_PSNR_PKT       : "PSNR_PKT",
               VPX_CODEC_CUSTOM_PKT     : "CUSTOM_PKT",
               }


#https://groups.google.com/a/webmproject.org/forum/?fromgroups#!msg/webm-discuss/f5Rmi-Cu63k/IXIzwVoXt_wJ
#"RGB is not supported.  You need to convert your source to YUV, and then compress that."
COLORSPACES = {}

CODECS = []
IF ENABLE_VP8 == True:
    CODECS.append("vp8")
    COLORSPACES["vp8"] = [b"YUV420P"]
IF ENABLE_VP9 == True:
    CODECS.append("vp9")
    vp9_cs = [b"YUV420P"]
    #this is the ABI version with libvpx 1.4.0:
    IF ENABLE_VP9_YUV444:
        if VPX_ENCODER_ABI_VERSION>=10:
            vp9_cs.append(b"YUV444P")
    COLORSPACES["vp9"] = vp9_cs


def init_module():
    log("vpx.encoder.init_module() info=%s", get_info())
    assert len(CODECS)>0, "no supported encodings!"
    log("supported codecs: %s", CODECS)
    log("supported colorspaces: %s", COLORSPACES)

def cleanup_module():
    log("vpx.encoder.cleanup_module()")

def get_abi_version():
    return VPX_ENCODER_ABI_VERSION

def get_version():
    v = vpx_codec_version_str()
    return v.decode("latin1")

def get_type():
    return "vpx"

def get_encodings():
    return CODECS

def get_input_colorspaces(encoding):
    assert encoding in get_encodings(), "invalid encoding: %s" % encoding
    return COLORSPACES[encoding]

def get_output_colorspaces(encoding, input_colorspace):
    assert encoding in get_encodings(), "invalid encoding: %s" % encoding
    csdict = COLORSPACES[input_colorspace]
    assert input_colorspace in csdict, "invalid input colorspace: %s" % input_colorspace
    #always unchanged in output:
    return [input_colorspace]


def get_info():
    global CODECS
    return {"version"       : get_version(),
            "encodings"     : CODECS,
            "abi_version"   : get_abi_version(),
            "build_config"  : vpx_codec_build_config()}


cdef const vpx_codec_iface_t  *make_codec_cx(encoding):
    IF ENABLE_VP8 == True:
        if encoding=="vp8":
            return vpx_codec_vp8_cx()
    IF ENABLE_VP9 == True:
        if encoding=="vp9":
            return vpx_codec_vp9_cx()
    raise Exception("unsupported encoding: %s" % encoding)


def get_spec(encoding, colorspace):
    assert encoding in CODECS, "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in get_input_colorspaces(encoding), "invalid colorspace: %s (must be one of %s)" % (colorspace, get_input_colorspaces(encoding))
    #quality: we only handle YUV420P but this is already accounted for by the subsampling factor
    #setup cost is reasonable (usually about 5ms)
    return video_codec_spec(encoding=encoding, output_colorspaces=[colorspace],
                            codec_class=Encoder, codec_type=get_type(), setup_cost=40)


cdef vpx_img_fmt_t get_vpx_colorspace(colorspace) except -1:
    if colorspace==b"YUV420P":
        return VPX_IMG_FMT_I420
    elif colorspace==b"YUV444P":
        return VPX_IMG_FMT_I444
    raise Exception("invalid colorspace %s" % colorspace)

def get_error_string(int err):
    estr = vpx_codec_err_to_string(<vpx_codec_err_t> err)[:]
    if not estr:
        return err
    return estr


cdef class Encoder:
    cdef unsigned long frames
    cdef vpx_codec_ctx_t *context
    cdef vpx_codec_enc_cfg_t *cfg
    cdef vpx_img_fmt_t pixfmt
    cdef int width
    cdef int height
    cdef int max_threads
    cdef double initial_bitrate_per_pixel
    cdef object encoding
    cdef char* src_format
    cdef int speed
    cdef int quality

    cdef object __weakref__

#init_context(w, h, src_format, encoding, quality, speed, scaling, options)
    def init_context(self, int width, int height, src_format, dst_formats, encoding, int quality, int speed, scaling, options):    #@DuplicatedSignature
        assert encoding in CODECS, "invalid encoding: %s" % encoding
        assert scaling==(1,1), "vpx does not handle scaling"
        assert encoding in get_encodings()
        assert src_format in get_input_colorspaces(encoding)
        self.src_format = src_format
        #log("vpx_encoder.init_context%s", (width, height, src_format, dst_formats, encoding, quality, speed, scaling, options))

        cdef const vpx_codec_iface_t *codec_iface = make_codec_cx(encoding)
        self.encoding = encoding
        self.width = width
        self.height = height
        self.speed = speed
        self.quality = quality
        self.frames = 0
        self.pixfmt = get_vpx_colorspace(self.src_format)
        try:
            self.max_threads = max(0, min(32, int(options.get("threads", VPX_THREADS))))
        except Exception as e:
            log.warn("error parsing number of threads: %s", e)
            self.max_threads =2

        self.cfg = <vpx_codec_enc_cfg_t *> xmemalign(sizeof(vpx_codec_enc_cfg_t))
        if self.cfg==NULL:
            raise Exception("failed to allocate memory for vpx encoder config")
        if vpx_codec_enc_config_default(codec_iface, self.cfg, 0)!=0:
            free(self.cfg)
            self.cfg = NULL
            raise Exception("failed to create vpx encoder config")
        log("%s codec defaults:", self.encoding)
        self.log_cfg()
        self.initial_bitrate_per_pixel = float(self.cfg.rc_target_bitrate) / self.cfg.g_w / self.cfg.g_h

        self.update_cfg()
        self.cfg.g_usage = USAGE_STREAM_FROM_SERVER
        self.cfg.g_profile = int(bool(self.src_format==b"YUV444P"))           #use 1 for YUV444P and RGB support
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
        #we choose when to use keyframes (never):
        self.cfg.kf_mode = VPX_KF_DISABLED
        self.cfg.kf_min_dist = 999999
        self.cfg.kf_max_dist = 999999

        self.context = <vpx_codec_ctx_t *> xmemalign(sizeof(vpx_codec_ctx_t))
        if self.context==NULL:
            free(self.cfg)
            self.cfg = NULL
            raise Exception("failed to allocate memory for vpx encoder context")
        memset(self.context, 0, sizeof(vpx_codec_ctx_t))

        log("our configuration:")
        self.log_cfg()
        cdef int ret = vpx_codec_enc_init_ver(self.context, codec_iface, self.cfg, 0, VPX_ENCODER_ABI_VERSION)
        if ret!=0:
            free(self.context)
            self.context = NULL
            log.warn("vpx_codec_enc_init_ver() returned %s", get_error_string(ret))
            raise Exception("failed to initialized vpx encoder: %s" % vpx_codec_error(self.context))
        log("vpx_codec_enc_init_ver for %s succeeded", encoding)

    def log_cfg(self):
        log(" target_bitrate=%s", self.cfg.rc_target_bitrate)
        log(" min_quantizer=%s", self.cfg.rc_min_quantizer)
        log(" max_quantizer=%s", self.cfg.rc_max_quantizer)
        log(" undershoot_pct=%s", self.cfg.rc_undershoot_pct)
        log(" overshoot_pct=%s", self.cfg.rc_overshoot_pct)

    cdef update_cfg(self):
        self.cfg.rc_undershoot_pct = 100
        self.cfg.rc_overshoot_pct = 100
        self.cfg.rc_target_bitrate = int(self.width * self.height * self.initial_bitrate_per_pixel)
        self.cfg.g_threads = self.max_threads
        self.cfg.rc_max_quantizer = int(max(0, min(63, self.quality * 0.63)))
        self.cfg.rc_min_quantizer = int(max(0, min(self.cfg.rc_max_quantizer, (self.quality-20)*0.63/1.5)))


    def __repr__(self):
        return "vpx.Encoder(%s)" % self.encoding

    def get_info(self):                     #@DuplicatedSignature
        info = get_info()
        info.update({"frames"    : self.frames,
                     "width"     : self.width,
                     "height"    : self.height,
                     "speed"     : self.speed,
                     "quality"   : self.quality,
                     "encoding"  : self.encoding,
                     "src_format": self.src_format,
                     "max_threads": self.max_threads})
        return info

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
        self.frames = 0
        self.pixfmt = 0
        self.width = 0
        self.height = 0
        self.max_threads = 0
        self.encoding = ""
        self.src_format = ""


    def compress_image(self, image, quality=-1, speed=-1, options={}):
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
            assert object_as_buffer(pixels[i], <const void**> &pic_buf, &pic_buf_len)==0
            pic_in[i] = pic_buf
            strides[i] = istrides[i]
        self.set_encoding_speed(speed)
        self.set_encoding_quality(quality)
        return self.do_compress_image(pic_in, strides), {"frame"    : self.frames,
                                                         "quality"  : min(99, self.quality),
                                                         "speed"    : self.speed}

    cdef do_compress_image(self, uint8_t *pic_in[3], int strides[3]):
        #actual compression (no gil):
        cdef vpx_image_t *image
        cdef const vpx_codec_cx_pkt_t *pkt
        cdef vpx_codec_iter_t iter = NULL
        cdef int frame_cnt = 0
        cdef int flags = 0
        cdef vpx_codec_err_t i                          #@DuplicatedSignature
        image = <vpx_image_t *> xmemalign(sizeof(vpx_image_t))
        memset(image, 0, sizeof(vpx_image_t))
        image.w = self.width
        image.h = self.height
        image.fmt = self.pixfmt
        for i in range(3):
            image.planes[i] = pic_in[i]
            image.stride[i] = strides[i]
        image.planes[3] = NULL
        image.stride[3] = 0
        image.d_w = self.width
        image.d_h = self.height
        #this is the chroma shift for YUV420P:
        #both X and Y are downscaled by 2^1
        if self.src_format==b"YUV420P":
            image.x_chroma_shift = 1
            image.y_chroma_shift = 1
        elif self.src_format==b"YUV444P":
            image.x_chroma_shift = 0
            image.y_chroma_shift = 0
        else:
            raise Exception("invalid colorspace: %s" % self.src_format)
            
        image.bps = 0
        if self.frames==0:
            flags |= VPX_EFLAG_FORCE_KF
        #deadline based on speed (also affects quality...)
        cdef long deadline
        if self.speed<10 or self.quality>=90:
            deadline = VPX_DL_BEST_QUALITY
        elif self.speed>=100:
            deadline = VPX_DL_REALTIME
        else:
            deadline = int(VPX_DL_GOOD_QUALITY * (100-self.speed) / 100.0)
        start = time.time()
        with nogil:
            ret = vpx_codec_encode(self.context, image, self.frames, 1, flags, deadline)
        if ret!=0:
            free(image)
            log.error("%s codec encoding error %s: %s", self.encoding, ret, get_error_string(ret))
            return None
        end = time.time()
        log("vpx_codec_encode for %s took %.1fms (deadline=%sms for speed=%s, quality=%s)", self.encoding, 1000.0*(end-start), deadline/1000, self.speed, self.quality)
        with nogil:
            pkt = vpx_codec_get_cx_data(self.context, &iter)
        end = time.time()
        if pkt.kind != VPX_CODEC_CX_FRAME_PKT:
            free(image)
            log.error("%s invalid packet type: %s", self.encoding, PACKET_KIND.get(pkt.kind, pkt.kind))
            return None
        self.frames += 1
        #we copy the compressed data here, we could manage the buffer instead
        #using vpx_codec_set_cx_data_buf every time with a wrapper for freeing it,
        #but since this is compressed data, no big deal
        img = (<char*> pkt.data.frame.buf)[:pkt.data.frame.sz]
        free(image)
        log("vpx returning %s image: %s bytes", self.encoding, len(img))
        return img

    def set_encoding_speed(self, int pct):
        self.speed = pct

    def set_encoding_quality(self, int pct):
        self.quality = pct
        self.update_cfg()
        cdef vpx_codec_err_t ret = vpx_codec_enc_config_set(self.context, self.cfg)
        assert ret==0, "failed to updated encoder configuration, vpx_codec_enc_config_set returned %s" % ret


def selftest():
    import sys
    assert sys.version[0]!='3', "currently broken with python3.."
    #fake empty buffer:
    w, h = 24, 16
    y = bytearray(b"\0" * (w*h))
    u = bytearray(b"\0" * (w*h//4))
    v = bytearray(b"\0" * (w*h//4))
    for encoding in get_encodings():
        e = Encoder()
        try:
            e.init_context(w, h, "YUV420P", ["YUV420P"], encoding, w, h, (1,1), {})
            from xpra.codecs.image_wrapper import ImageWrapper
            image = ImageWrapper(0, 0, w, h, [y, u ,v], "YUV420P", 32, [w, w/2, w/2], planes=ImageWrapper.PACKED, thread_safe=True)
            c = e.compress_image(image)
            #import binascii
            #print("compressed data(%s)=%s" % (encoding, binascii.hexlify(str(c))))
        finally:
            e.clean()
