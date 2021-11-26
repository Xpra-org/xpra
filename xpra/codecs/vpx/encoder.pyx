# This file is part of Xpra.
# Copyright (C) 2012-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import math
from collections import deque
from time import monotonic

from xpra.log import Logger
log = Logger("encoder", "vpx")

from xpra.codecs.codec_constants import video_spec, get_subsampling_divs
from xpra.os_util import WIN32, OSX, POSIX, BITS
from xpra.util import AtomicInteger, envint, envbool, typedict

from libc.stdint cimport uint8_t
from libc.stdlib cimport free, malloc
from libc.string cimport memset


SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")

cdef int default_nthreads = max(1, int(math.sqrt(os.cpu_count()+1)))
cdef int VPX_THREADS = envint("XPRA_VPX_THREADS", default_nthreads)

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


ctypedef long vpx_img_fmt_t
ctypedef void vpx_codec_iface_t

DEF USAGE_STREAM_FROM_SERVER    = 0x0
DEF USAGE_LOCAL_FILE_PLAYBACK   = 0x1
DEF USAGE_CONSTRAINED_QUALITY   = 0x2
DEF USAGE_CONSTANT_QUALITY      = 0x3

DEF VPX_CODEC_USE_HIGHBITDEPTH = 0x40000


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

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
    cdef int VPX_IMG_FMT_I44416
    cdef int VPX_IMG_FMT_HIGHBITDEPTH
    cdef int VPX_IMG_FMT_HAS_ALPHA

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
    ctypedef int vpx_bit_depth_t
    ctypedef struct vpx_codec_enc_cfg_t:
        unsigned int g_usage
        unsigned int g_threads
        unsigned int g_profile
        unsigned int g_w
        unsigned int g_h
        vpx_bit_depth_t g_bit_depth
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

CODECS = ("vp8", "vp9")
COLORSPACES["vp8"] = ("YUV420P", )
#this is the ABI version with libvpx 1.4.0:
assert VPX_ENCODER_ABI_VERSION>=10, "vpx abi version is too old: %i (minimum is 10)" % VPX_ENCODER_ABI_VERSION
if VPX_ENCODER_ABI_VERSION<=23:
    COLORSPACES["vp9"] = ("YUV420P", "YUV444P", )
else:
    COLORSPACES["vp9"] = ("YUV420P", "YUV444P", "YUV444P10")

VP9_RANGE = 3
#as of 1.8:
#VPX_ENCODER_ABI_VERSION=14+VPX_CODEC_ABI_VERSION
#VPX_CODEC_ABI_VERSION=4+VPX_IMAGE_ABI_VERSION
#VPX_IMAGE_ABI_VERSION=5
if VPX_ENCODER_ABI_VERSION>=14+4+5:
    VP9_RANGE = 4


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
    b = vpx_codec_version_str()
    vstr = b.decode("latin1")
    log("vpx_codec_version_str()=%s", vstr)
    return vstr.lstrip("v")

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
    if input_colorspace=="YUV444P10":
        return ["r210",]
    return [input_colorspace]


generation = AtomicInteger()
def get_info():
    global CODECS, MAX_SIZE
    b = vpx_codec_build_config()
    info = {
        "version"       : get_version(),
        "encodings"     : CODECS,
        "abi_version"   : get_abi_version(),
        "counter"       : generation.get(),
        "build_config"  : b.decode("latin1"),
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
    "vp8"   : (8192, 4096),
    "vp9"   : (8192, 4096),
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
        has_lossless_mode = colorspace.startswith("YUV444P")
        speed = 20
        quality = 50 + 50*int(has_lossless_mode)
        if VPX_ENCODER_ABI_VERSION>=11:
            #libvpx 1.5 made some significant performance improvements with vp9:
            speed = 40
    return video_spec(encoding=encoding, input_colorspace=colorspace, output_colorspaces=[colorspace],
                      has_lossless_mode=has_lossless_mode,
                      codec_class=Encoder, codec_type=get_type(),
                      quality=quality, speed=speed,
                      size_efficiency=60,
                      setup_cost=20, max_w=max_w, max_h=max_h)


cdef vpx_img_fmt_t get_vpx_colorspace(colorspace) except -1:
    if colorspace=="YUV420P":
        return VPX_IMG_FMT_I420
    if colorspace=="YUV444P" and ENABLE_VP9_YUV444:
        return VPX_IMG_FMT_I444
    if colorspace=="YUV444P10" and ENABLE_VP9_YUV444:
        return VPX_IMG_FMT_I44416
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
    cdef unsigned int generation
    cdef unsigned long bandwidth_limit
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
    def init_context(self, device_context, int width, int height, src_format, dst_formats, encoding, int quality, int speed, scaling, options):
        log("vpx init_context%s", (device_context, width, height, src_format, dst_formats, encoding, quality, speed, scaling, options))
        assert encoding in CODECS, "invalid encoding: %s" % encoding
        assert scaling==(1,1), "vpx does not handle scaling"
        assert encoding in get_encodings()
        assert src_format in get_input_colorspaces(encoding)
        if BITS==32 and WIN32:
            dmaxw, dmaxh = MAX_SIZE[encoding]
            if width>dmaxw or height>dmaxh:
                #this can crash on win32, don't even try it
                #(the unit tests would otherwise crash)
                raise Exception("invalid dimensions %ix%i - maximum is %ix%i" % (width, height, dmaxw, dmaxh))

        self.src_format = src_format

        cdef const vpx_codec_iface_t *codec_iface = make_codec_cx(encoding)
        cdef vpx_codec_flags_t flags = 0
        self.encoding = encoding
        self.width = width
        self.height = height
        self.speed = speed
        self.quality = quality
        self.bandwidth_limit = options.intget("bandwidth-limit", 0)
        self.lossless = 0
        self.frames = 0
        self.last_frame_times = deque(maxlen=200)
        self.pixfmt = get_vpx_colorspace(self.src_format)
        try:
            #no point having too many threads if the height is small, also avoids a warning:
            self.max_threads = max(0, min(int(options.intget("threads", VPX_THREADS)), roundup(height, 64)//64, 32))
        except Exception as e:
            log.error("Error parsing number of threads: %s", e)
            self.max_threads = 2

        if vpx_codec_enc_config_default(codec_iface, &self.cfg, 0)!=0:
            raise Exception("failed to create vpx encoder config")
        log("%s codec defaults:", self.encoding)
        self.log_cfg()
        self.initial_bitrate_per_pixel = self.cfg.rc_target_bitrate / self.cfg.g_w / self.cfg.g_h
        log("initial_bitrate_per_pixel(%i, %i, %i)=%.3f", self.cfg.g_w, self.cfg.g_h, self.cfg.rc_target_bitrate, self.initial_bitrate_per_pixel)

        self.update_cfg()
        self.cfg.g_usage = USAGE_STREAM_FROM_SERVER
        if self.src_format=="YUV444P":
            self.cfg.g_profile = 1
            self.cfg.g_bit_depth = 8
        elif self.src_format=="YUV444P10":
            self.cfg.g_profile = 3
            self.cfg.g_bit_depth = 10
            flags |= VPX_CODEC_USE_HIGHBITDEPTH
        else:
            self.cfg.g_profile = 0
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

        self.context = <vpx_codec_ctx_t *> malloc(sizeof(vpx_codec_ctx_t))
        if self.context==NULL:
            raise Exception("failed to allocate memory for vpx encoder context")
        memset(self.context, 0, sizeof(vpx_codec_ctx_t))

        log("our configuration:")
        self.log_cfg()
        cdef int ret = vpx_codec_enc_init_ver(self.context, codec_iface, &self.cfg, flags, VPX_ENCODER_ABI_VERSION)
        if ret!=0:
            free(self.context)
            self.context = NULL
            log("vpx_codec_enc_init_ver() returned %s", get_error_string(ret))
            raise Exception("failed to instantiate %s encoder with ABI version %s: %s" % (encoding, VPX_ENCODER_ABI_VERSION, self.codec_error_str()))
        log("vpx_codec_enc_init_ver for %s succeeded", encoding)
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
        self.generation = generation.increase()
        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+"vpx-"+str(self.generation)+".%s" % encoding
            self.file = open(filename, 'wb')
            log.info("saving %s stream to %s", encoding, filename)

    def codec_error_str(self):
        return vpx_codec_error(self.context).decode("latin1")

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
        bitrate_kbps = int(self.width * self.height * self.initial_bitrate_per_pixel)
        if self.bandwidth_limit>0:
            #vpx bitrate values are in Kbps:
            bitrate_kbps = min(self.bandwidth_limit//1024, bitrate_kbps)
        bitrate_kbps = max(16, min(15000, bitrate_kbps))
        log("update_cfg() bitrate(%i,%i,%.3f,%i)=%iKbps",
            self.width, self.height, self.initial_bitrate_per_pixel, self.bandwidth_limit, bitrate_kbps)
        self.cfg.rc_target_bitrate = max(16, min(15000, bitrate_kbps))
        self.cfg.g_threads = self.max_threads
        self.cfg.rc_min_quantizer = MAX(0, MIN(63, int((80-self.quality) * 0.63)))
        self.cfg.rc_max_quantizer = MAX(self.cfg.rc_min_quantizer, MIN(63, int((100-self.quality) * 0.63)))

    def is_ready(self):
        return True


    def __repr__(self):
        return "vpx.Encoder(%s)" % self.encoding

    def get_info(self) -> dict:
        info = get_info()
        info.update({
            "frames"    : int(self.frames),
            "width"     : self.width,
            "height"    : self.height,
            "speed"     : self.speed,
            "quality"   : self.quality,
            "lossless"  : bool(self.lossless),
            "generation" : self.generation,
            "encoding"  : self.encoding,
            "src_format": self.src_format,
            "max_threads": self.max_threads,
            "bandwidth-limit" : int(self.bandwidth_limit),
            })
        #calculate fps:
        cdef unsigned int f = 0
        cdef double now = monotonic()
        cdef double last_time = now
        cdef double cut_off = now-10.0
        cdef double ms_per_frame = 0
        for start,end in tuple(self.last_frame_times):
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

    def get_type(self):
        return  "vpx"

    def get_src_format(self):
        return self.src_format

    def __dealloc__(self):
        self.clean()

    def clean(self):
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


    def compress_image(self, device_context, image, quality=-1, speed=-1, options=None):
        cdef uint8_t *pic_in[3]
        cdef int strides[3]
        assert self.context!=NULL
        pixels = image.get_pixels()
        istrides = image.get_rowstride()
        assert image.get_pixel_format()==self.src_format, "invalid input format %s, expected %s" % (image.get_pixel_format, self.src_format)
        assert image.get_width()==self.width, "invalid image width %s, expected %s" % (image.get_width(), self.width)
        assert image.get_height()==self.height, "invalid image height %s, expected %s" % (image.get_height(), self.height)
        assert pixels, "failed to get pixels from %s" % image
        assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
        assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
        cdef unsigned int Bpp = 1 + int(self.src_format.endswith("P10"))
        divs = get_subsampling_divs(self.src_format)
        cdef unsigned long bandwidth_limit = typedict(options or {}).intget("bandwidth-limit", self.bandwidth_limit)

        if bandwidth_limit!=self.bandwidth_limit:
            self.bandwidth_limit = bandwidth_limit
            self.update_cfg()
        if speed>=0:
            self.set_encoding_speed(speed)
        if quality>=0:
            self.set_encoding_quality(quality)

        cdef Py_buffer py_buf[3]
        for i in range(3):
            memset(&py_buf[i], 0, sizeof(Py_buffer))
        try:
            for i in range(3):
                xdiv, ydiv = divs[i]
                if PyObject_GetBuffer(pixels[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                    raise Exception("failed to read pixel data from %s" % type(pixels[i]))
                assert istrides[i]>=self.width*Bpp//xdiv, "invalid stride %i for width %i" % (istrides[i], self.width)
                assert py_buf[i].len>=istrides[i]*(self.height//ydiv), "invalid buffer length %i for plane %s, at least %i needed" % (
                    py_buf[i].len, "YUV"[i], istrides[i]*(self.height//ydiv))
                pic_in[i] = <uint8_t *> py_buf[i].buf
                strides[i] = istrides[i]
            return self.do_compress_image(pic_in, strides), {
                "csc"       : self.src_format,
                "frame"     : int(self.frames),
                #"quality"  : min(99+self.lossless, self.quality),
                #"speed"    : self.speed,
                }
        finally:
            for i in range(3):
                if py_buf[i].buf:
                    PyBuffer_Release(&py_buf[i])

    cdef do_compress_image(self, uint8_t *pic_in[3], int strides[3]):
        #actual compression (no gil):
        cdef vpx_codec_iter_t iter = NULL
        cdef int flags = 0
        cdef vpx_codec_err_t i

        cdef vpx_image_t *image = <vpx_image_t *> malloc(sizeof(vpx_image_t))
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
        elif self.src_format.startswith("YUV444P"):
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
            deadline_str = "REALTIME"
        elif self.speed<10 or self.quality>=90:
            deadline = VPX_DL_BEST_QUALITY
            deadline_str = "BEST_QUALITY"
        else:
            deadline = MAX(2, VPX_DL_GOOD_QUALITY * (90-self.speed) // 100)
            #cap the deadline at 250ms, which is already plenty
            deadline = MIN(250*1000, deadline)
            deadline_str = "%8.3fms" % deadline
        cdef double start = monotonic()
        with nogil:
            ret = vpx_codec_encode(self.context, image, self.frames, 1, flags, deadline)
        if ret!=0:
            free(image)
            log.error("%s codec encoding error %s: %s", self.encoding, ret, get_error_string(ret))
            return None
        cdef double end = monotonic()
        log("vpx_codec_encode for %s took %ims (deadline=%16s for speed=%s, quality=%s)", self.encoding, 1000.0*(end-start), deadline_str, self.speed, self.quality)
        cdef const vpx_codec_cx_pkt_t *pkt
        with nogil:
            pkt = vpx_codec_get_cx_data(self.context, &iter)
        if pkt==NULL or pkt.kind!=VPX_CODEC_CX_FRAME_PKT:
            free(image)
            log.error("%s invalid packet type: %s", self.encoding, PACKET_KIND.get(pkt.kind, pkt.kind))
            return None
        self.frames += 1
        #we copy the compressed data here, we could manage the buffer instead
        #using vpx_codec_set_cx_data_buf every time with a wrapper for freeing it,
        #but since this is compressed data, no big deal
        cdef size_t size = pkt.data.frame.sz
        img = (<char*> pkt.data.frame.buf)[:size]
        free(image)
        log("vpx returning %s data: %s bytes", self.encoding, size)
        end = monotonic()
        self.last_frame_times.append((start, end))
        if self.file and size>0:
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
            range = VP9_RANGE
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
        if full and POSIX and not OSX:
            #but first, try to figure out if we have enough memory to do this
            try:
                import psutil
                freemem_MB = psutil.virtual_memory().available//1024//1024
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
                maxw, maxh = get_encoder_max_size(encoder, encoding, limit_w=8192, limit_h=8192)
                dmaxw, dmaxh = MAX_SIZE[encoding]
                assert maxw>=dmaxw and maxh>=dmaxh, "%s is limited to %ix%i for %s and not %ix%i" % (encoder, maxw, maxh, encoding, dmaxw, dmaxh)
                MAX_SIZE[encoding] = maxw, maxh
            log("%s max dimensions: %s", encoder, MAX_SIZE)
    finally:
        SAVE_TO_FILE = temp
