# This file is part of Xpra.
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False, wraparound=False, cdivision=True
from __future__ import absolute_import

import os

from xpra.log import Logger
log = Logger("encoder", "x264")

from xpra.util import nonl, envint, envbool, typedict, AtomicInteger
from xpra.os_util import bytestostr, strtobytes
from xpra.codecs.codec_constants import get_subsampling_divs, video_spec
from collections import deque
from xpra.buffers.membuf cimport object_as_buffer

from xpra.monotonic_time cimport monotonic_time
from libc.stdint cimport int64_t, uint64_t, uint8_t, uintptr_t


THREADS = envint("XPRA_X264_THREADS")
SLICED_THREADS = envint("XPRA_X264_SLICED_THREADS", 1)
MIN_SLICED_THREADS_SPEED = envint("XPRA_X264_SLICED_THREADS", 60)
LOGGING = os.environ.get("XPRA_X264_LOGGING", "WARNING")
PROFILE = os.environ.get("XPRA_X264_PROFILE")
SUPPORT_24BPP = envbool("XPRA_X264_SUPPORT_24BPP")
TUNE = os.environ.get("XPRA_X264_TUNE")
LOG_NALS = envbool("XPRA_X264_LOG_NALS")
SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")


cdef extern from "string.h":
    int vsnprintf(char * s, size_t n, const char * format, va_list arg)

cdef extern from "stdint.h":
    pass
cdef extern from "inttypes.h":
    pass

cdef extern from "stdarg.h":
    ctypedef struct va_list:
        pass
    ctypedef struct fake_type:
        pass
    void va_start(va_list, void* arg)
    void* va_arg(va_list, fake_type)
    void va_end(va_list)
    fake_type int_type "int"

cdef extern from "x264.h":
    int X264_KEYINT_MAX_INFINITE

    int X264_BUILD

    int X264_LOG_DEBUG
    int X264_LOG_INFO
    int X264_LOG_WARNING
    int X264_LOG_ERROR

    int X264_CSP_I420
    int X264_CSP_I422
    int X264_CSP_I444
    int X264_CSP_BGR
    int X264_CSP_BGRA
    int X264_CSP_RGB

    int X264_B_ADAPT_NONE
    int X264_B_ADAPT_FAST
    int X264_B_ADAPT_TRELLIS

    #enum
    int X264_ME_DIA
    int X264_ME_HEX
    int X264_ME_UMH
    int X264_ME_ESA
    int X264_ME_TESA

    #enum nal_unit_type_e
    int NAL_UNKNOWN
    int NAL_SLICE
    int NAL_SLICE_DPA
    int NAL_SLICE_DPB
    int NAL_SLICE_DPC
    int NAL_SLICE_IDR
    int NAL_SEI
    int NAL_SPS
    int NAL_PPS
    int NAL_AUD
    int NAL_FILLER

    #enum nal_priority_e
    int NAL_PRIORITY_DISPOSABLE
    int NAL_PRIORITY_LOW
    int NAL_PRIORITY_HIGH
    int NAL_PRIORITY_HIGHEST

    #frame type
    int X264_TYPE_AUTO              # Let x264 choose the right type
    int X264_TYPE_KEYFRAME
    int X264_TYPE_IDR
    int X264_TYPE_I
    int X264_TYPE_P
    int X264_TYPE_BREF
    int X264_TYPE_B

    int X264_WEIGHTP_NONE

    const char * const *x264_preset_names

    ctypedef struct rc:
        int         i_rc_method
        int         i_qp_constant       #0 to (51 + 6*(x264_bit_depth-8)). 0=lossless
        int         i_qp_min            #min allowed QP value
        int         i_qp_max            #max allowed QP value
        int         i_qp_step           #max QP step between frames

        int         i_bitrate
        float       f_rf_constant       #1pass VBR, nominal QP
        float       f_rf_constant_max   #In CRF mode, maximum CRF as caused by VBV
        float       f_rate_tolerance
        int         i_vbv_max_bitrate
        int         i_vbv_buffer_size
        float       f_vbv_buffer_init   #<=1: fraction of buffer_size. >1: kbit
        float       f_ip_factor
        float       f_pb_factor

        int         i_aq_mode           #psy adaptive QP. (X264_AQ_*)
        float       f_aq_strength
        int         b_mb_tree           #Macroblock-tree ratecontrol
        int         i_lookahead

        # 2pass
        int         b_stat_write        #Enable stat writing in psz_stat_out
        char        *psz_stat_out       #output filename (in UTF-8) of the 2pass stats file
        int         b_stat_read         #Read stat from psz_stat_in and use it
        char        *psz_stat_in        #input filename (in UTF-8) of the 2pass stats file

        # 2pass params (same as ffmpeg ones)
        float       f_qcompress         #0.0 => cbr, 1.0 => constant qp
        float       f_qblur             #temporally blur quants
        float       f_complexity_blur   #temporally blur complexity
        #x264_zone_t *zones              #ratecontrol overrides
        int         i_zones             #number of zone_t's
        char        *psz_zones          #alternate method of specifying zones

    ctypedef struct analyse:
        int         i_me_method         # motion estimation algorithm to use (X264_ME_*)
        int         i_me_range          # integer pixel motion estimation search range (from predicted mv) */
        int         i_mv_range          # maximum length of a mv (in pixels). -1 = auto, based on level */
        int         i_mv_range_thread   # minimum space between threads. -1 = auto, based on number of threads. */
        int         i_subpel_refine     # subpixel motion estimation quality */
        int         i_weighted_pred     # weighting for P-frames
        int         b_weighted_bipred   # implicit weighting for B-frames

    ctypedef struct x264_param_t:
        unsigned int cpu
        int i_threads           #encode multiple frames in parallel
        int i_lookahead_threads #multiple threads for lookahead analysis
        int b_sliced_threads    #Whether to use slice-based threading
        int b_deterministic     #whether to allow non-deterministic optimizations when threaded
        int b_cpu_independent   #force canonical behavior rather than cpu-dependent optimal algorithms
        int i_sync_lookahead    #threaded lookahead buffer

        int i_width
        int i_height
        int i_csp               #CSP of encoded bitstream
        int i_level_idc
        int i_frame_total       #number of frames to encode if known, else 0

        int i_log_level
        void* pf_log

        #Bitstream parameters
        int i_frame_reference   #Maximum number of reference frames
        int i_dpb_size          #Force a DPB size larger than that implied by B-frames and reference frames
                                #Useful in combination with interactive error resilience.
        int i_keyint_max        #Force an IDR keyframe at this interval
        int i_keyint_min        #Scenecuts closer together than this are coded as I, not IDR.
        int i_scenecut_threshold#how aggressively to insert extra I frames
        int b_intra_refresh     #Whether or not to use periodic intra refresh instead of IDR frames.

        int i_bframe            #how many b-frame between 2 references pictures
        int i_bframe_adaptive
        int i_bframe_bias
        int i_bframe_pyramid    #Keep some B-frames as references: 0=off, 1=strict hierarchical, 2=normal
        int b_open_gop
        int b_bluray_compat
        #older x264 builds do not support this:
        #int b_opencl            #use OpenCL when available

        int b_cabac
        int b_deblocking_filter
        int b_interlaced
        int b_constrained_intra

        rc  rc                  #rate control
        analyse analyse

        int b_vfr_input         #VFR input. If 1, use timebase and timestamps for ratecontrol purposes. If 0, use fps only

    ctypedef struct x264_t:
        pass
    ctypedef struct x264_nal_t:
        int i_ref_idc
        int i_type
        int b_long_startcode
        int i_first_mb
        int i_last_mb
        int i_payload
        uint8_t *p_payload
    ctypedef struct x264_image_t:
        int i_csp           #Colorspace
        int i_plane         #Number of image planes
        int i_stride[4]     #Strides for each plane
        uint8_t *plane[4]   #Pointers to each plane
    ctypedef struct x264_image_properties_t:
        pass
    ctypedef struct x264_hrd_t:
        pass
    ctypedef struct x264_sei_t:
        pass
    ctypedef struct x264_picture_t:
        int i_type          #In: force picture type (if not auto)
        int i_qpplus1       #In: force quantizer for != X264_QP_AUTO
        int i_pic_struct    #In: pic_struct, for pulldown/doubling/etc...used only if b_pic_struct=1.
                            #use pic_struct_e for pic_struct inputs
                            #Out: pic_struct element associated with frame
        int b_keyframe      #Out: whether this frame is a keyframe.  Important when using modes that result in
                            #SEI recovery points being used instead of IDR frames.
        int64_t i_pts       #In: user pts, Out: pts of encoded picture (user)
                            #Out: frame dts. When the pts of the first frame is close to zero,
                            #initial frames may have a negative dts which must be dealt with by any muxer
        x264_param_t *param #In: custom encoding parameters to be set from this frame forwards (..)
        x264_image_t img    #In: raw image data
                            #Out: Out: reconstructed image data
        x264_image_properties_t prop    #In: optional information to modify encoder decisions for this frame
                            #Out: information about the encoded frame */
        x264_hrd_t hrd_timing   #Out: HRD timing information. Output only when i_nal_hrd is set.
        x264_sei_t extra_sei#In: arbitrary user SEI (e.g subtitles, AFDs)
        void *opaque        #private user data. copied from input to output frames.

    void x264_picture_init(x264_picture_t *pic) nogil

    int x264_param_default_preset(x264_param_t *param, const char *preset, const char *tune)
    int x264_param_apply_profile(x264_param_t *param, const char *profile)
    void x264_encoder_parameters(x264_t *context, x264_param_t *param)
    int x264_encoder_reconfig(x264_t *context, x264_param_t *param)

    x264_t *x264_encoder_open(x264_param_t *param)
    void x264_encoder_close(x264_t *context)

    int x264_encoder_encode(x264_t *context, x264_nal_t **pp_nal, int *pi_nal, x264_picture_t *pic_in, x264_picture_t *pic_out ) nogil
    int x264_encoder_delayed_frames(x264_t *)
    int x264_encoder_maximum_delayed_frames(x264_t *h)


cdef set_f_rf(x264_param_t *param, float q):
    param.rc.f_rf_constant = q

cdef const char * const *get_preset_names():
    return x264_preset_names;


#we choose presets from 1 to 7
#(we exclude placebo)
cdef int get_preset_for_speed(int speed):
    if speed > 99:
        #only allow "ultrafast" if pct > 99
        return 0
    return 7 - max(0, min(6, speed / 15))

#the x264 quality option ranges from 0 (best) to 51 (lowest)
cdef float get_x264_quality(int pct, char *profile):
    if pct>=100 and profile:
        #easier to compare as python strings:
        pyiprofile = str(profile)
        pycprofile = str(PROFILE_HIGH444_PREDICTIVE)
        if pycprofile==pyiprofile:
            return 0.0
    return <float> (50.0 - (min(100, max(0, pct)) * 49.0 / 100.0))

ADAPT_TYPES = {
               X264_B_ADAPT_NONE        : "NONE",
               X264_B_ADAPT_FAST        : "FAST",
               X264_B_ADAPT_TRELLIS     : "TRELLIS",
               }

SLICE_TYPES = {
    X264_TYPE_AUTO  : "auto",
    X264_TYPE_IDR   : "IDR",
    X264_TYPE_I     : "I",
    X264_TYPE_P     : "P",
    X264_TYPE_BREF  : "BREF",
    X264_TYPE_B     : "B",
    X264_TYPE_KEYFRAME  : "KEYFRAME",
    }

ME_TYPES = {
    X264_ME_DIA     : "DIA",
    X264_ME_HEX     : "HEX",
    X264_ME_UMH     : "UMH",
    X264_ME_ESA     : "ESA",
    X264_ME_TESA    : "TESA",
    }

NAL_TYPES = {
    NAL_UNKNOWN     : "unknown",
    NAL_SLICE       : "slice",
    NAL_SLICE_DPA   : "slice-dpa",
    NAL_SLICE_DPB   : "slice-dpb",
    NAL_SLICE_DPC   : "slice-dpc",
    NAL_SLICE_IDR   : "slice-idr",
    NAL_SEI         : "sei",
    NAL_SPS         : "sps",
    NAL_PPS         : "pps",
    NAL_AUD         : "aud",
    NAL_FILLER      : "filler",
    }

NAL_PRIORITIES = {
    NAL_PRIORITY_DISPOSABLE : "disposable",
    NAL_PRIORITY_LOW        : "low",
    NAL_PRIORITY_HIGH       : "high",
    NAL_PRIORITY_HIGHEST    : "highest",
    }


cdef char *PROFILE_BASELINE = "baseline"
cdef char *PROFILE_MAIN     = "main"
cdef char *PROFILE_HIGH     = "high"
cdef char *PROFILE_HIGH10   = "high10"
cdef char *PROFILE_HIGH422  = "high422"
cdef char *PROFILE_HIGH444_PREDICTIVE = "high444"
I420_PROFILES = [PROFILE_BASELINE, PROFILE_MAIN, PROFILE_HIGH, PROFILE_HIGH10, PROFILE_HIGH422, PROFILE_HIGH444_PREDICTIVE]
I422_PROFILES = [PROFILE_HIGH422, PROFILE_HIGH444_PREDICTIVE]
I444_PROFILES = [PROFILE_HIGH444_PREDICTIVE]
RGB_PROFILES = [PROFILE_HIGH444_PREDICTIVE]

COLORSPACE_FORMATS = {
    "YUV420P"   : (X264_CSP_I420,    PROFILE_HIGH,                  I420_PROFILES),
    "YUV422P"   : (X264_CSP_I422,    PROFILE_HIGH422,               I422_PROFILES),
    "YUV444P"   : (X264_CSP_I444,    PROFILE_HIGH444_PREDICTIVE,    I444_PROFILES),
    "BGRA"      : (X264_CSP_BGRA,    PROFILE_HIGH444_PREDICTIVE,    RGB_PROFILES),
    "BGRX"      : (X264_CSP_BGRA,    PROFILE_HIGH444_PREDICTIVE,    RGB_PROFILES),
    }
if SUPPORT_24BPP:
    COLORSPACE_FORMATS.update({
        "BGR"       : (X264_CSP_BGR,     PROFILE_HIGH444_PREDICTIVE,    RGB_PROFILES),
        "RGB"       : (X264_CSP_RGB,     PROFILE_HIGH444_PREDICTIVE,    RGB_PROFILES),
        })

COLORSPACES = {
    "YUV420P"   : ("YUV420P",),
    "YUV422P"   : ("YUV422P",),
    "YUV444P"   : ("YUV444P",),
    "BGRA"      : ("BGRA",),
    "BGRX"      : ("BGRX",),
    }
if SUPPORT_24BPP:
    COLORSPACES.update({
        "BGR"       : ("BGR",),
        "RGB"       : ("RGB",),
        })


def init_module():
    log("enc_x264.init_module()")

def cleanup_module():
    log("enc_x264.cleanup_module()")

def get_version():
    return X264_BUILD

def get_type():
    return "x264"

generation = AtomicInteger()
def get_info():
    global COLORSPACES, MAX_WIDTH, MAX_HEIGHT
    return {
        "version"   : get_version(),
        "max-size"  : (MAX_WIDTH, MAX_HEIGHT),
        "generation": generation.get(),
        "formats"   : tuple(COLORSPACES.keys()),
        }

def get_encodings():
    return ["h264"]

def get_input_colorspaces(encoding):
    assert encoding in get_encodings()
    return  COLORSPACES.keys()

def get_output_colorspaces(encoding, input_colorspace):
    assert encoding in get_encodings()
    assert input_colorspace in COLORSPACES
    return COLORSPACES[input_colorspace]

if X264_BUILD<146:
    #untested, but should be OK for 4k:
    MAX_WIDTH, MAX_HEIGHT = 4096, 4096
else:
    #actual limits (which we cannot reach because we hit OOM):
    #MAX_WIDTH, MAX_HEIGHT = 16384, 16384
    MAX_WIDTH, MAX_HEIGHT = 8192, 4096

def get_spec(encoding, colorspace):
    assert encoding in get_encodings(), "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES.keys())
    #we can handle high quality and any speed
    #setup cost is moderate (about 10ms)
    has_lossless_mode = colorspace in ("YUV444P", "BGR", "BGRA", "BGRX", "RGB")
    return video_spec(encoding=encoding, output_colorspaces=COLORSPACES[colorspace], has_lossless_mode=has_lossless_mode,
                            codec_class=Encoder, codec_type=get_type(),
                            quality=60+40*int(has_lossless_mode), speed=60,
                            size_efficiency=40,
                            setup_cost=20, width_mask=0xFFFE, height_mask=0xFFFE, max_w=MAX_WIDTH, max_h=MAX_HEIGHT)


#maps a log level to one of our logger functions:
LOGGERS = {
           X264_LOG_ERROR   : log.error,
           X264_LOG_WARNING : log.warn,
           X264_LOG_INFO    : log.info,
           X264_LOG_DEBUG   : log.debug,
           }

#maps a log level string to the actual constant:
LOG_LEVEL = {
             "ERROR"    : X264_LOG_ERROR,
             "WARNING"  : X264_LOG_WARNING,
             "WARN"     : X264_LOG_WARNING,
             "INFO"     : X264_LOG_INFO,
             #getting segfaults with "DEBUG" level logging...
             #so this is currently disabled
             #"DEBUG"    : X264_LOG_DEBUG,
             }.get(LOGGING.upper(), X264_LOG_WARNING)


#the static logging function we want x264 to use:
cdef void X264_log(void *p_unused, int level, const char *psz_fmt, va_list arg) with gil:
    cdef char buffer[256]
    cdef int r
    r = vsnprintf(buffer, 256, psz_fmt, arg)
    if r<0:
        log.error("X264_log: vsnprintf returned %s on format string '%s'", r, psz_fmt)
        return
    s = nonl(bytestostr(buffer[:r]).rstrip("\n\r"))
    logger = LOGGERS.get(level, log.info)
    logger("X264: %s", s)


cdef class Encoder:
    cdef unsigned long frames
    cdef x264_t *context
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned int fast_decode
    #cdef int opencl
    cdef object src_format
    cdef object source
    cdef object profile
    cdef object tune
    cdef double time
    cdef int colorspace
    cdef int preset
    cdef int quality
    cdef int speed
    cdef int b_frames
    cdef int delayed_frames
    cdef int export_nals
    cdef unsigned long long bytes_in
    cdef unsigned long long bytes_out
    cdef object last_frame_times
    cdef object file
    cdef object frame_types
    cdef uint64_t first_frame_timestamp

    cdef object __weakref__

    def init_context(self, unsigned int width, unsigned int height, src_format, dst_formats, encoding, int quality, int speed, scaling, options={}):
        options = typedict(options)
        global COLORSPACE_FORMATS, generation
        cs_info = COLORSPACE_FORMATS.get(src_format)
        assert cs_info is not None, "invalid source format: %s, must be one of: %s" % (src_format, COLORSPACE_FORMATS.keys())
        assert encoding=="h264", "invalid encoding: %s" % encoding
        assert scaling==(1,1), "x264 does not handle scaling"
        self.width = width
        self.height = height
        self.quality = quality
        self.speed = speed
        #self.opencl = USE_OPENCL and width>=32 and height>=32
        self.source = options.strget("source", "unknown")      #ie: "video"
        self.b_frames = options.intget("b-frames", 0)
        self.fast_decode = options.boolget("h264.fast-decode", False)
        if self.fast_decode:
            speed = max(70, speed)
        self.preset = get_preset_for_speed(speed)
        self.src_format = src_format
        self.colorspace = cs_info[0]
        self.frames = 0
        self.frame_types = {}
        self.last_frame_times = deque(maxlen=200)
        self.time = 0
        self.first_frame_timestamp = 0
        self.profile = self._get_profile(options, self.src_format)
        self.export_nals = options.intget("h264.export-nals", 0)
        if self.profile is not None and self.profile not in cs_info[2]:
            log.warn("invalid profile specified for %s: %s (must be one of: %s)" % (src_format, self.profile, cs_info[2]))
            self.profile = None
        if self.profile is None:
            self.profile = cs_info[1]
            log("using default profile=%s", bytestostr(self.profile))
        self.init_encoder(options)
        gen = generation.increase()
        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+"x264-"+str(gen)+".%s" % encoding
            self.file = open(filename, 'wb')
            log.info("saving %s stream to %s", encoding, filename)

    def get_tune(self):
        log("x264: get_tune() TUNE=%s, fast_decode=%s, source=%s", TUNE, self.fast_decode, self.source)
        if TUNE:
            return TUNE
        if self.source=="video":
            return b"film"
        #return "animation"
        return b"zerolatency"

    cdef init_encoder(self, options):
        cdef x264_param_t param
        cdef const char *preset
        preset = get_preset_names()[self.preset]
        self.tune = self.get_tune()
        x264_param_default_preset(&param, strtobytes(preset), strtobytes(self.tune))
        x264_param_apply_profile(&param, self.profile)
        self.tune_param(&param, options)

        self.context = x264_encoder_open(&param)
        cdef int maxd = x264_encoder_maximum_delayed_frames(self.context)
        log("x264 context=%#x, %7s %4ix%-4i quality=%i, speed=%i, source=%s", <uintptr_t> self.context, self.src_format, self.width, self.height, self.quality, self.speed, self.source)
        log("x264 params: %s", self.get_param_info(&param))
        assert self.context!=NULL,  "context initialization failed for format %s" % self.src_format

    cdef tune_param(self, x264_param_t *param, options):
        param.i_threads = THREADS
        param.i_lookahead_threads = 0
        if self.speed>=MIN_SLICED_THREADS_SPEED and not self.fast_decode:
            param.b_sliced_threads = SLICED_THREADS
        #we never lose frames or use seeking, so no need for regular I-frames:
        param.i_keyint_max = X264_KEYINT_MAX_INFINITE
        #we don't want IDR frames either:
        param.i_keyint_min = X264_KEYINT_MAX_INFINITE
        param.b_intra_refresh = 0   #no intra refresh
        param.b_open_gop = 1        #allow open gop
        #param.b_opencl = self.opencl
        param.i_bframe = self.b_frames
        param.rc.i_lookahead = min(param.rc.i_lookahead, self.b_frames-1)
        param.b_vfr_input = 0
        if not self.b_frames:
            param.i_sync_lookahead = 0
            param.rc.b_mb_tree = 0
        else:
            if param.i_bframe_adaptive==X264_B_ADAPT_TRELLIS:
                param.i_bframe_adaptive = X264_B_ADAPT_FAST
        if self.source!="video":
            #specifically told this is not video,
            #so use a simple motion search:
            param.analyse.i_me_method = X264_ME_DIA
        set_f_rf(param, get_x264_quality(self.quality, self.profile))
        #client can tune these options:
        param.b_open_gop = options.boolget("h264.open-gop", param.b_open_gop)
        param.b_deblocking_filter = not self.fast_decode and options.boolget("h264.deblocking-filter", param.b_deblocking_filter)
        param.b_cabac = not self.fast_decode and options.boolget("h264.cabac", param.b_cabac)
        param.b_bluray_compat = options.boolget("h264.bluray-compat", param.b_bluray_compat)
        if self.fast_decode:
            param.analyse.b_weighted_bipred = 0
            param.analyse.i_weighted_pred = X264_WEIGHTP_NONE
        #input format:
        param.i_width = self.width
        param.i_height = self.height
        param.i_csp = self.colorspace
        #logging hook:
        param.pf_log = <void *> X264_log
        param.i_log_level = LOG_LEVEL


    def clean(self):                        #@DuplicatedSignature
        log("x264 close context %#x", <uintptr_t> self.context)
        cdef x264_t *context = self.context
        if context!=NULL:
            self.context = NULL
            x264_encoder_close(context)
        self.frames = 0
        self.width = 0
        self.height = 0
        self.fast_decode = 0
        self.src_format = ""
        self.source = None
        self.profile = None
        self.time = 0
        self.colorspace = 0
        self.preset = 0
        self.quality = 0
        self.speed = 0
        self.bytes_in = 0
        self.bytes_out = 0
        self.last_frame_times = []
        self.first_frame_timestamp = 0
        f = self.file
        if f:
            self.file = None
            f.close()


    def get_info(self):             #@DuplicatedSignature
        cdef double pps
        if self.profile is None:
            return {}
        info = get_info()
        info.update({
            "profile"       : self.profile,
            "preset"        : get_preset_names()[self.preset],
            "fast-decode"   : bool(self.fast_decode),
            "b-frames"      : self.b_frames,
            "tune"          : self.tune or "",
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            #"opencl"        : bool(self.opencl),
            "speed"         : self.speed,
            "quality"       : self.quality,
            "lossless"      : self.quality==100,
            "src_format"    : self.src_format,
            "source"        : self.source,
            "version"       : get_version(),
            "frame-types"   : self.frame_types,
            "delayed"       : self.delayed_frames,
            })
        cdef x264_param_t param
        x264_encoder_parameters(self.context, &param)
        info["params"] = self.get_param_info(&param)
        if self.bytes_in>0 and self.bytes_out>0:
            info.update({
                "bytes_in"  : int(self.bytes_in),
                "bytes_out" : int(self.bytes_out),
                "ratio_pct" : int(100.0 * self.bytes_out / self.bytes_in),
                })
        if self.frames>0 and self.time>0:
            pps = float(self.width) * float(self.height) * float(self.frames) / self.time
            info.update({
                "total_time_ms"     : int(self.time*1000.0),
                "pixels_per_second" : int(pps),
                })
        #calculate fps:
        cdef unsigned int f = 0
        cdef double now = monotonic_time()
        cdef double last_time = now
        cdef double cut_off = now-10.0
        cdef double ms_per_frame = 0
        for start,end in tuple(self.last_frame_times):
            if end>cut_off:
                f += 1
                last_time = min(last_time, end)
                ms_per_frame += (end-start)
        if f>0 and last_time<now:
            info.update({
                "fps"           : int(0.5+f/(now-last_time)),
                "ms_per_frame"  : int(1000.0*ms_per_frame/f),
                })
        return info

    cdef get_param_info(self, x264_param_t *param):
        return {
            "me"                :   {
                "type"              : ME_TYPES.get(param.analyse.i_me_method, param.analyse.i_me_method),
                "me-range"          : param.analyse.i_me_range,
                "mv-range"          : param.analyse.i_mv_range,
                "weighted-pred"     : param.analyse.i_weighted_pred,
                },
            "vfr-input"         : bool(param.b_vfr_input),
            "lookahead"         : param.rc.i_lookahead,
            "mb-tree"           : bool(param.rc.b_mb_tree),
            "bframe-adaptive"   :  ADAPT_TYPES.get(param.i_bframe_adaptive, param.i_bframe_adaptive),
            "open-gop"          : bool(param.b_open_gop),
            "bluray-compat"     : bool(param.b_bluray_compat),
            "cabac"             : bool(param.b_cabac),
            "deblocking-filter" : bool(param.b_deblocking_filter),
            "intra-refresh"     : bool(param.b_intra_refresh),
            "interlaced"        : bool(param.b_interlaced),
            "constrained_intra" : bool(param.b_constrained_intra),
            "threads"           : {0 : "auto"}.get(param.i_threads, param.i_threads),
            "sliced-threads"    : bool(param.b_sliced_threads),
            }

    def __repr__(self):
        if self.src_format is None:
            return "x264_encoder(uninitialized)"
        return "x264_encoder(%s - %sx%s)" % (self.src_format, self.width, self.height)

    def is_closed(self):
        return self.context==NULL

    def get_encoding(self):
        return "h264"

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):                     #@DuplicatedSignature
        return  "x264"

    def get_src_format(self):
        return self.src_format

    cdef _get_profile(self, options, csc_mode):
        #use the environment as default if present:
        profile = os.environ.get("XPRA_X264_%s_PROFILE" % csc_mode, PROFILE)
        #now see if the client has requested a different value:
        profile = options.get("h264.%s.profile" % csc_mode, profile)
        return options.get("x264.%s.profile" % csc_mode, profile)


    def compress_image(self, image, int quality=-1, int speed=-1, options={}):
        cdef x264_picture_t pic_in
        cdef uint8_t *pic_buf
        cdef Py_ssize_t pic_buf_len = 0
        cdef char *out
        cdef int i                        #@DuplicatedSignature

        assert image.get_width()>=self.width
        assert image.get_height()>=self.height
        assert image.get_pixel_format()==self.src_format

        if self.first_frame_timestamp==0:
            self.first_frame_timestamp = image.get_timestamp()

        source = options.get("source", "unknown")
        b_frames = options.get("b-frames", 0)
        if source!=self.source or self.b_frames!=b_frames:
            #some options have changed:
            log("compress_image: reconfig b-frames=%s, source=%s (from %s, %s)", b_frames, source, self.b_frames, self.source)
            self.source = source
            self.b_frames = b_frames
            self.reconfig_tune()

        pixels = image.get_pixels()
        istrides = image.get_rowstride()
        assert pixels, "failed to get pixels from %s" % image

        x264_picture_init(&pic_in)

        if self.src_format.find("RGB")>=0 or self.src_format.find("BGR")>=0:
            assert len(pixels)>0
            assert istrides>0
            assert object_as_buffer(pixels, <const void**> &pic_buf, &pic_buf_len)==0, "unable to convert %s to a buffer" % type(pixels)
            for i in range(3):
                pic_in.img.plane[i] = pic_buf
                pic_in.img.i_stride[i] = istrides
            self.bytes_in += pic_buf_len
        else:
            assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
            assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
            for i in range(3):
                assert object_as_buffer(pixels[i], <const void**> &pic_buf, &pic_buf_len)==0, "unable to convert %s to a buffer (plane=%s)" % (type(pixels[i]), i)
                pic_in.img.plane[i] = pic_buf
                pic_in.img.i_stride[i] = istrides[i]

        pic_in.img.i_csp = self.colorspace
        pic_in.img.i_plane = 3
        pic_in.i_pts = image.get_timestamp()-self.first_frame_timestamp
        return self.do_compress_image(&pic_in, quality, speed)

    cdef do_compress_image(self, x264_picture_t *pic_in, int quality=-1, int speed=-1):
        cdef x264_nal_t *nals = NULL
        cdef int i_nals = 0
        cdef x264_picture_t pic_out
        cdef int frame_size = 0
        assert self.context!=NULL
        cdef double start = monotonic_time()

        if speed>=0:
            self.set_encoding_speed(speed)
        else:
            speed = self.speed
        if quality>=0:
            self.set_encoding_quality(quality)
        else:
            quality = self.quality

        with nogil:
            x264_picture_init(&pic_out)
            frame_size = x264_encoder_encode(self.context, &nals, &i_nals, pic_in, &pic_out)
        if frame_size < 0:
            log.error("x264 encoding error: frame_size is invalid!")
            return None
        self.delayed_frames = x264_encoder_delayed_frames(self.context)
        if i_nals==0:
            if self.delayed_frames>0:
                log("x264 encode %i delayed frames after %i", self.delayed_frames, self.frames)
                return None, {
                    "delayed" : self.delayed_frames,
                    "frame"   : self.frames,
                    }
            raise Exception("x264_encoder_encode produced no data (frame=%i, frame-size=%i, b-frames=%s, delayed-frames=%i)" % (self.frames, frame_size, self.b_frames, self.delayed_frames))
        slice_type = SLICE_TYPES.get(pic_out.i_type, pic_out.i_type)
        self.frame_types[slice_type] = self.frame_types.get(slice_type, 0)+1
        log("x264 encode %7s frame %5i as %4s slice with %i nals, tune=%s, total %7i bytes, keyframe=%-5s, delayed=%i", self.src_format, self.frames, slice_type, i_nals, self.tune, frame_size, bool(pic_out.b_keyframe), self.delayed_frames)
        bnals = []
        nal_indexes = []
        cdef unsigned int index = 0
        for i in range(i_nals):
            out = <char *>nals[i].p_payload
            cdata = out[:nals[i].i_payload]
            bnals.append(cdata)
            index += nals[i].i_payload
            nal_indexes.append(index)
            if LOG_NALS:
                log.info(" nal %s priority:%10s, type:%10s, payload=%#x, payload size=%i",
                         i, NAL_PRIORITIES.get(nals[i].i_ref_idc, nals[i].i_ref_idc), NAL_TYPES.get(nals[i].i_type, nals[i].i_type), <uintptr_t> nals[i].p_payload, nals[i].i_payload)
        cdata = b"".join(bnals)
        if len(cdata)!=frame_size:
            log.warn("Warning: h264 nals do not match frame size")
            log.warn(" expected %i bytes, but got %i nals and %i bytes", frame_size, len(bnals), len(cdata))
        self.bytes_out += frame_size
        #restore speed and quality if we temporarily modified them:
        if speed>=0:
            self.set_encoding_speed(self.speed)
        if quality>=0:
            self.set_encoding_quality(self.quality)
        #info for client:
        client_options = {
                "frame"     : int(self.frames),
                "pts"       : pic_out.i_pts,
                #"quality"   : max(0, min(100, quality)),
                #"speed"     : max(0, min(100, speed)),
                "type"      : slice_type,
                }
        if self.delayed_frames>0:
            client_options["delayed"] = self.delayed_frames
        if self.export_nals:
            client_options["nals"] = nal_indexes
        #accounting:
        cdef double end = monotonic_time()
        self.time += end-start
        self.frames += 1
        self.last_frame_times.append((start, end))
        assert self.context!=NULL
        if self.file and frame_size>0:
            self.file.write(cdata)
            self.file.flush()
        return cdata, client_options

    def flush(self, unsigned long frame_no):
        if self.frames>frame_no or self.context==NULL:
            return None, {}
        self.delayed_frames = x264_encoder_delayed_frames(self.context)
        log("x264 flush(%i) %i delayed frames", frame_no, self.delayed_frames)
        if self.delayed_frames<=0:
            return None, {}
        cdef x264_nal_t *nals = NULL
        cdef int i_nals = 0
        cdef x264_picture_t pic_out
        cdef int frame_size = 0
        x264_picture_init(&pic_out)
        return self.do_compress_image(NULL)


    def set_encoding_speed(self, int pct):
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        assert self.context!=NULL, "context is closed!"
        cdef x264_param_t param                     #@DuplicatedSignature
        cdef int new_preset = get_preset_for_speed(pct)
        if new_preset == self.preset:
            return
        self.speed = pct
        #retrieve current parameters:
        x264_encoder_parameters(self.context, &param)
        #apply new preset:
        self.tune = self.get_tune()
        x264_param_default_preset(&param, get_preset_names()[new_preset], self.tune)
        #ensure quality remains what it was:
        self.do_reconfig_tune(&param)
        self.preset = new_preset

    def set_encoding_quality(self, int pct):
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        if self.quality==pct:
            return
        if abs(self.quality - pct)<=4 and pct!=100 and self.quality!=100:
            #not enough of a change to bother (but always change to/from 100)
            return
        #adjust quality:
        self.quality = pct
        self.reconfig_tune()

    def reconfig_tune(self):
        cdef x264_param_t param
        x264_encoder_parameters(self.context, &param)
        self.do_reconfig_tune(&param)

    cdef do_reconfig_tune(self, x264_param_t *param):
        assert self.context!=NULL, "context is closed!"
        #adjust quality:
        set_f_rf(param, get_x264_quality(self.quality, self.profile))
        self.tune_param(param, typedict())
        #apply it:
        if x264_encoder_reconfig(self.context, param)!=0:
            raise Exception("x264_encoder_reconfig failed")


def selftest(full=False):
    global SAVE_TO_FILE
    from xpra.codecs.codec_checks import testencoder, get_encoder_max_sizes
    from xpra.codecs.enc_x264 import encoder
    temp = SAVE_TO_FILE
    try:
        SAVE_TO_FILE = None
        assert testencoder(encoder, full)
        #this is expensive, so don't run it unless "full" is set:
        if full:
            global MAX_WIDTH, MAX_HEIGHT
            maxw, maxh = get_encoder_max_sizes(encoder)
            assert maxw>=MAX_WIDTH and maxh>=MAX_HEIGHT, "%s is limited to %ix%i and not %ix%i" % (encoder, maxw, maxh, MAX_WIDTH, MAX_HEIGHT)
            MAX_WIDTH, MAX_HEIGHT = maxw, maxh
            log.info("%s max dimensions: %ix%i", encoder, MAX_WIDTH, MAX_HEIGHT)
    finally:
        SAVE_TO_FILE = temp
