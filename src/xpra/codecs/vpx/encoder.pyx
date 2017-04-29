# This file is part of Xpra.
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import os
from collections import deque

from xpra.log import Logger
log = Logger("encoder", "vpx")

from xpra.codecs.codec_constants import video_spec
from xpra.os_util import bytestostr, WIN32, OSX
from xpra.util import AtomicInteger, envint, envbool
from xpra.buffers.membuf cimport memalign, object_as_buffer

from libc.stdint cimport uint8_t
from xpra.monotonic_time cimport monotonic_time


SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")

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
cdef int VPX_THREADS = envint("XPRA_VPX_THREADS", max(1, cpus-1))

cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)

cdef int ENABLE_VP9_YUV444 = envbool("XPRA_VP9_YUV444", True)
cdef int ENABLE_VP9_TILING = envbool("XPRA_VP9_TILING", False)


cdef inline int MIN(int a, int b):
    if a<=b:
        return a
    return b
cdef inline int MAX(int a, int b):
    if a>=b:
        return a
    return b


from libc.stdint cimport int64_t

cdef extern from "string.h":
    void *memset(void *ptr, int value, size_t num) nogil
    void free(void *ptr) nogil


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
    #this should be a vararg function, but we only use it with a single int argument,
    #so define it that way (easier on cython):
    vpx_codec_err_t vpx_codec_control_(vpx_codec_ctx_t *ctx, int ctrl_id, int value)

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
    const vpx_codec_iface_t *vpx_codec_vp8_cx()
    const vpx_codec_iface_t *vpx_codec_vp9_cx()

cdef extern from "vpx/vpx_encoder.h":
    int VPX_ENCODER_ABI_VERSION
    #vpx_rc_mode
    int VPX_VBR         #Variable Bit Rate (VBR) mode
    int VPX_CBR         #Constant Bit Rate (CBR) mode
    int VPX_CQ          #Constant Quality (CQ) mode
    #function to set number of tile columns:
    int VP9E_SET_TILE_COLUMNS
    #function to set encoder internal speed settings:
    int VP8E_SET_CPUUSED
    #function to enable/disable periodic Q boost:
    int VP9E_SET_FRAME_PERIODIC_BOOST
    int VP9E_SET_LOSSLESS
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

CODECS = ["vp8", "vp9"]
COLORSPACES["vp8"] = ["YUV420P"]
CODECS.append("vp9")
vp9_cs = ["YUV420P"]
#this is the ABI version with libvpx 1.4.0:
if ENABLE_VP9_YUV444:
    if VPX_ENCODER_ABI_VERSION>=10:
        vp9_cs.append("YUV444P")
    else:
        log("encoder abi is too low to enable YUV444P: %s", VPX_ENCODER_ABI_VERSION)
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
    vstr = v.decode("latin1")
    log("vpx_codec_version_str()=%s", vstr)
    return vstr

def get_type():
    return "vpx"

def get_encodings():
    return CODECS

def get_input_colorspaces(encoding):
    assert encoding in get_encodings(), "invalid encoding: %s" % encoding
    return COLORSPACES[encoding]

def get_output_colorspaces(encoding, input_colorspace):
    assert encoding in get_encodings(), "invalid encoding: %s" % encoding
    csoptions = COLORSPACES[encoding]
    assert input_colorspace in csoptions, "invalid input colorspace: %s, %s only supports %s" % (input_colorspace, encoding, csoptions)
    #always unchanged in output:
    return [input_colorspace]


generation = AtomicInteger()
def get_info():
    global CODECS, MAX_SIZE
    info = {
        "version"       : get_version(),
        "encodings"     : CODECS,
        "abi_version"   : get_abi_version(),
        "generation"    : generation.get(),
        "build_config"  : vpx_codec_build_config(),
        }
    for e, maxsize in MAX_SIZE.items():
        info["%s.max-size" % e] = maxsize
    for k,v in COLORSPACES.items():
        info["%s.colorspaces" % k] = v
    return info


cdef const vpx_codec_iface_t  *make_codec_cx(encoding):
    if encoding=="vp8":
        return vpx_codec_vp8_cx()
    if encoding=="vp9":
        return vpx_codec_vp9_cx()
    raise Exception("unsupported encoding: %s" % encoding)


#educated guess:
MAX_SIZE = {
    "vp8"   : (8192, 8192),
    "vp9"   : (16384, 8192),
    }
#no idea why, but this is the default on win32:
if WIN32:
    MAX_SIZE["vp9"] = (4096, 4096)


def get_spec(encoding, colorspace):
    assert encoding in CODECS, "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in get_input_colorspaces(encoding), "invalid colorspace: %s (must be one of %s)" % (colorspace, get_input_colorspaces(encoding))
    #quality: we only handle YUV420P but this is already accounted for by the subsampling factor
    #setup cost is reasonable (usually about 5ms)
    global MAX_SIZE
    max_w, max_h = MAX_SIZE[encoding]
    if encoding=="vp8":
        has_lossless_mode = False
        speed = 50
        quality = 50
    else:
        lossless_mode = colorspace=="YUV444P"
        speed = 20
        quality = 50 + 50*int(lossless_mode)
        if VPX_ENCODER_ABI_VERSION>=11:
            #libvpx 1.5 made some significant performance improvements with vp9:
            speed = 40
    return video_spec(encoding=encoding, output_colorspaces=[colorspace], has_lossless_mode=has_lossless_mode,
                            codec_class=Encoder, codec_type=get_type(),
                            quality=quality, speed=speed,
                            size_efficiency=80,
                            setup_cost=20, max_w=max_w, max_h=max_h)


cdef vpx_img_fmt_t get_vpx_colorspace(colorspace) except -1:
    if colorspace=="YUV420P":
        return VPX_IMG_FMT_I420
    if colorspace=="YUV444P" and ENABLE_VP9_YUV444:
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
    cdef vpx_codec_enc_cfg_t cfg
    cdef vpx_img_fmt_t pixfmt
    cdef int width
    cdef int height
    cdef int max_threads
    cdef double initial_bitrate_per_pixel
    cdef object encoding
    cdef object src_format
    cdef int speed
    cdef int quality
    cdef int lossless
    cdef object last_frame_times
    cdef object file

    cdef object __weakref__

#init_context(w, h, src_format, encoding, quality, speed, scaling, options)
    def init_context(self, int width, int height, src_format, dst_formats, encoding, int quality, int speed, scaling, options):    #@DuplicatedSignature
        assert encoding in CODECS, "invalid encoding: %s" % encoding
        assert scaling==(1,1), "vpx does not handle scaling"
        assert encoding in get_encodings()
        assert src_format in get_input_colorspaces(encoding)
        self.src_format = bytestostr(src_format)
        #log("vpx_encoder.init_context%s", (width, height, src_format, dst_formats, encoding, quality, speed, scaling, options))

        cdef const vpx_codec_iface_t *codec_iface = make_codec_cx(encoding)
        self.encoding = encoding
        self.width = width
        self.height = height
        self.speed = speed
        self.quality = quality
        self.lossless = 0
        self.frames = 0
        self.last_frame_times = deque(maxlen=200)
        self.pixfmt = get_vpx_colorspace(self.src_format)
        try:
            #no point having too many threads if the height is small, also avoids a warning:
            self.max_threads = max(0, min(int(options.get("threads", VPX_THREADS)), roundup(height, 32)//32*2, 32))
        except Exception as e:
            log.warn("error parsing number of threads: %s", e)
            self.max_threads = 2

        if vpx_codec_enc_config_default(codec_iface, &self.cfg, 0)!=0:
            raise Exception("failed to create vpx encoder config")
        log("%s codec defaults:", self.encoding)
        self.log_cfg()
        self.initial_bitrate_per_pixel = float(self.cfg.rc_target_bitrate) / self.cfg.g_w / self.cfg.g_h
        log("initial_bitrate_per_pixel(%i, %i, %i)=%.3f", self.cfg.g_w, self.cfg.g_h, self.cfg.rc_target_bitrate, self.initial_bitrate_per_pixel)

        self.update_cfg()
        self.cfg.g_usage = USAGE_STREAM_FROM_SERVER
        self.cfg.g_profile = int(bool(self.src_format=="YUV444P"))          #use 1 for YUV444P and RGB support
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

        self.context = <vpx_codec_ctx_t *> memalign(sizeof(vpx_codec_ctx_t))
        if self.context==NULL:
            raise Exception("failed to allocate memory for vpx encoder context")
        memset(self.context, 0, sizeof(vpx_codec_ctx_t))

        log("our configuration:")
        self.log_cfg()
        cdef int ret = vpx_codec_enc_init_ver(self.context, codec_iface, &self.cfg, 0, VPX_ENCODER_ABI_VERSION)
        if ret!=0:
            free(self.context)
            self.context = NULL
            log("vpx_codec_enc_init_ver() returned %s", get_error_string(ret))
            raise Exception("failed to instantiate %s encoder with ABI version %s: %s" % (encoding, VPX_ENCODER_ABI_VERSION, bytestostr(vpx_codec_error(self.context))))
        log("vpx_codec_enc_init_ver for %s succeeded", encoding)
        cdef vpx_codec_err_t ctrl
        if encoding=="vp9" and ENABLE_VP9_TILING and width>=256:
            tile_columns = 0
            if width>=256:
                tile_columns = 1
            elif width>=512:
                tile_columns = 2
            elif width>=1024:
                tile_columns = 3
            self.codec_control("tile columns", VP9E_SET_TILE_COLUMNS, tile_columns)
        if encoding=="vp9":
            #disable periodic Q boost which causes latency spikes:
            self.codec_control("periodic Q boost", VP9E_SET_FRAME_PERIODIC_BOOST, 0)
        self.do_set_encoding_speed(speed)
        self.do_set_encoding_quality(quality)
        gen = generation.increase()
        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+"vpx-"+str(gen)+".%s" % encoding
            self.file = open(filename, 'wb')
            log.info("saving %s stream to %s", encoding, filename)


    def codec_control(self, info, int attr, int value):
        cdef vpx_codec_err_t ctrl = vpx_codec_control_(self.context, attr, value)
        log("%s setting %s to %s", self.encoding, info, value)
        if ctrl!=0:
            log.warn("failed to set %s to %s: %s (%s)", info, value, get_error_string(ctrl), ctrl)
        return ctrl==0


    def log_cfg(self):
        log(" target_bitrate=%s", self.cfg.rc_target_bitrate)
        log(" min_quantizer=%s", self.cfg.rc_min_quantizer)
        log(" max_quantizer=%s", self.cfg.rc_max_quantizer)
        log(" undershoot_pct=%s", self.cfg.rc_undershoot_pct)
        log(" overshoot_pct=%s", self.cfg.rc_overshoot_pct)

    cdef update_cfg(self):
        self.cfg.rc_undershoot_pct = 100
        self.cfg.rc_overshoot_pct = 100
        self.cfg.rc_target_bitrate = max(16, min(15000, int(self.width * self.height * self.initial_bitrate_per_pixel)))
        log("update_cfg() bitrate(%i,%i,%.3f)=%i", self.width, self.height, self.initial_bitrate_per_pixel, self.cfg.rc_target_bitrate)
        self.cfg.g_threads = self.max_threads
        self.cfg.rc_min_quantizer = MAX(0, MIN(63, int((80-self.quality) * 0.63)))
        self.cfg.rc_max_quantizer = MAX(self.cfg.rc_min_quantizer, MIN(63, int((100-self.quality) * 0.63)))


    def __repr__(self):
        return "vpx.Encoder(%s)" % self.encoding

    def get_info(self):                     #@DuplicatedSignature
        info = get_info()
        info.update({
            "frames"    : self.frames,
            "width"     : self.width,
            "height"    : self.height,
            "speed"     : self.speed,
            "quality"   : self.quality,
            "lossless"  : bool(self.lossless),
            "encoding"  : self.encoding,
            "src_format": self.src_format,
            "max_threads": self.max_threads,
            })
        #calculate fps:
        cdef unsigned int f = 0
        cdef double now = monotonic_time()
        cdef double last_time = now
        cdef double cut_off = now-10.0
        cdef double ms_per_frame = 0
        for start,end in list(self.last_frame_times):
            if end>cut_off:
                f += 1
                last_time = min(last_time, end)
                ms_per_frame += (end-start)
        if f>0 and last_time<now:
            info["fps"] = int(0.5+f/(now-last_time))
            info["ms_per_frame"] = int(1000.0*ms_per_frame/f)
        info.update({
            "target_bitrate"   : self.cfg.rc_target_bitrate,
            "min-quantizer"    : self.cfg.rc_min_quantizer,
            "max-quantizer"    : self.cfg.rc_max_quantizer,
            "undershoot-pct"   : self.cfg.rc_undershoot_pct,
            "overshoot-pct"    : self.cfg.rc_overshoot_pct,
            })
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
        self.frames = 0
        self.pixfmt = 0
        self.width = 0
        self.height = 0
        self.max_threads = 0
        self.encoding = ""
        self.src_format = ""
        f = self.file
        if f:
            self.file = None
            f.close()


    def compress_image(self, image, quality=-1, speed=-1, options={}):
        cdef uint8_t *pic_in[3]
        cdef int strides[3]
        cdef uint8_t *pic_buf = NULL
        cdef Py_ssize_t pic_buf_len = 0
        assert self.context!=NULL
        pixels = image.get_pixels()
        istrides = image.get_rowstride()
        assert image.get_pixel_format()==self.src_format, "invalid input format %s, expected %s" % (image.get_pixel_format, self.src_format)
        assert image.get_width()==self.width, "invalid image width %s, expected %s" % (image.get_width(), self.width)
        assert image.get_height()==self.height, "invalid image height %s, expected %s" % (image.get_height(), self.height)
        assert pixels, "failed to get pixels from %s" % image
        assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
        assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
        for i in range(3):
            assert object_as_buffer(pixels[i], <const void**> &pic_buf, &pic_buf_len)==0
            pic_in[i] = pic_buf
            strides[i] = istrides[i]
        if speed>=0:
            self.set_encoding_speed(speed)
        if quality>=0:
            self.set_encoding_quality(quality)
        return self.do_compress_image(pic_in, strides), {
            "frame"    : self.frames,
            #"quality"  : min(99+self.lossless, self.quality),
            #"speed"    : self.speed,
            }

    cdef do_compress_image(self, uint8_t *pic_in[3], int strides[3]):
        #actual compression (no gil):
        cdef vpx_image_t *image
        cdef const vpx_codec_cx_pkt_t *pkt
        cdef vpx_codec_iter_t iter = NULL
        cdef int frame_cnt = 0
        cdef int flags = 0
        cdef vpx_codec_err_t i                          #@DuplicatedSignature

        cdef double start, end
        image = <vpx_image_t *> memalign(sizeof(vpx_image_t))
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
        if self.src_format=="YUV420P":
            image.x_chroma_shift = 1
            image.y_chroma_shift = 1
        elif self.src_format=="YUV444P":
            image.x_chroma_shift = 0
            image.y_chroma_shift = 0
        else:
            raise Exception("invalid colorspace: %s" % self.src_format)

        image.bps = 0
        if self.frames==0:
            flags |= VPX_EFLAG_FORCE_KF
        #deadline based on speed (also affects quality...)
        cdef unsigned long deadline
        if self.speed>=90 or self.encoding=="vp9":
            deadline = VPX_DL_REALTIME
        elif self.speed<10 or self.quality>=90:
            deadline = VPX_DL_BEST_QUALITY
        else:
            deadline = MAX(2, VPX_DL_GOOD_QUALITY * (90-self.speed) // 100)
            #cap the deadline at 250ms, which is already plenty
            deadline = MIN(250*1000, deadline)
        start = monotonic_time()
        with nogil:
            ret = vpx_codec_encode(self.context, image, self.frames, 1, flags, deadline)
        if ret!=0:
            free(image)
            log.error("%s codec encoding error %s: %s", self.encoding, ret, get_error_string(ret))
            return None
        end = monotonic_time()
        log("vpx_codec_encode for %s took %ims (deadline=%8.3fms for speed=%s, quality=%s)", self.encoding, 1000.0*(end-start), deadline/1000.0, self.speed, self.quality)
        with nogil:
            pkt = vpx_codec_get_cx_data(self.context, &iter)
        end = monotonic_time()
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
        end = monotonic_time()
        self.last_frame_times.append((start, end))
        if self.file and pkt.data.frame.sz>0:
            self.file.write(img)
            self.file.flush()
        return img

    def set_encoding_speed(self, int pct):
        if self.speed==pct:
            return
        self.speed = pct
        self.do_set_encoding_speed(pct)

    cdef do_set_encoding_speed(self, int speed):
        #Valid range for VP8: -16..16
        #Valid range for VP9: -8..8
        #But we only use positive values, negative values are just too slow
        cdef int minv = 4
        cdef int range = 12
        if self.encoding=="vp9":
            minv = 5
            range = 3
        #note: we don't use the full range since the percentages are mapped to -20% to +120%
        cdef int value = (speed-20)*3*range//200
        value = minv + MIN(range, MAX(0, value))
        self.codec_control("cpu speed", VP8E_SET_CPUUSED, value)

    def set_encoding_quality(self, int pct):
        if self.quality==pct:
            return
        self.quality = pct
        self.do_set_encoding_quality(pct)

    cdef do_set_encoding_quality(self, int pct):
        self.update_cfg()
        cdef int lossless = 0
        if self.encoding=="vp9":
            if self.codec_control("lossless", VP9E_SET_LOSSLESS, pct==100):
                lossless = 1
        self.lossless = lossless
        cdef vpx_codec_err_t ret = vpx_codec_enc_config_set(self.context, &self.cfg)
        assert ret==0, "failed to updated encoder configuration, vpx_codec_enc_config_set returned %s" % ret


def selftest(full=False):
    global CODECS, SAVE_TO_FILE
    from xpra.codecs.codec_checks import testencoder, get_encoder_max_size
    from xpra.codecs.vpx import encoder
    temp = SAVE_TO_FILE
    try:
        SAVE_TO_FILE = None
        CODECS = testencoder(encoder, full)
        #this is expensive, so don't run it unless "full" is set:
        if full and os.name=="posix" and not OSX:
            #but first, try to figure out if we have enough memory to do this
            try:
                import subprocess
                p = subprocess.Popen("free -b | grep ^Mem:", shell=True, stdout=subprocess.PIPE)
                stdout = p.communicate()[0]
                out = stdout.decode('utf-8')
                freemem_MB = int(out.split(" ")[-1])//1024//1024
                if freemem_MB<=4096:
                    log.info("system has only %iMB of memory available, skipping vpx max-size tests", freemem_MB)
                    full = False
                else:
                    log.info("system has %.1fGB of memory available, running full tests", freemem_MB/1024.0)
            except Exception as e:
                log.info("failed to detect free memory: %s", e)
                log.info("skipping vpx max-size tests")
                full = False
        if full:
            global MAX_SIZE
            for encoding in get_encodings():
                maxw, maxh = get_encoder_max_size(encoder, encoding, limit_w=8192, limit_h=4096)
                dmaxw, dmaxh = MAX_SIZE[encoding]
                assert maxw>=dmaxw and maxh>=dmaxh, "%s is limited to %ix%i and not %ix%i" % (encoder, maxw, maxh, dmaxw, dmaxh)
                MAX_SIZE[encoding] = maxw, maxh
            log("%s max dimensions: %s", encoder, MAX_SIZE)
    finally:
        SAVE_TO_FILE = temp
