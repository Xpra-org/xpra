# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import os

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_X264_DEBUG")
error = log.error
X264_THREADS = int(os.environ.get("XPRA_X264_THREADS", "0"))

include "constants.pxi"

from xpra.codecs.codec_constants import get_subsampling_divs, RGB_FORMATS, codec_spec

cdef extern from "string.h":
    void * memcpy ( void * destination, void * source, size_t num )
    void * memset ( void * ptr, int value, size_t num )

from libc.stdint cimport int64_t, uint8_t

cdef extern from *:
    ctypedef unsigned long size_t

cdef extern from "stdint.h":
    pass
cdef extern from "inttypes.h":
    pass

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1


cdef extern from "x264.h":
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

    int x264_param_default_preset(x264_param_t *param, const char *preset, const char *tune)
    int x264_param_apply_profile(x264_param_t *param, const char *profile)
    void x264_encoder_parameters(x264_t *context, x264_param_t *param)
    int x264_encoder_reconfig(x264_t *context, x264_param_t *param)

    x264_t *x264_encoder_open(x264_param_t *param)
    void x264_encoder_close(x264_t *context)

    int x264_encoder_encode(x264_t *context, x264_nal_t **pp_nal, int *pi_nal, x264_picture_t *pic_in, x264_picture_t *pic_out ) nogil

cdef extern from "enc_x264.h":

    const char * const *const get_preset_names()

    void set_f_rf(x264_param_t *param, float v)


def get_version():
    return constants["X264_BUILD"]

def get_type():
    return "x264"

def get_encodings():
    return ["h264"]

def init_module():
    #nothing to do!
    pass


#we choose presets from 1 to 7
#(we exclude placebo)
cdef int get_preset_for_speed(int speed):
    if speed > 99:
        #only allow "ultrafast" if pct > 99
        return 0
    return 7 - max(0, min(6, speed / 15))

#the x264 quality option ranges from 0 (best) to 51 (lowest)
cdef float get_x264_quality(int pct):
    return 50.0 - (min(100, max(0, pct)) * 49.0 / 100.0)


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

COLORSPACES = {}
for x264_enum, colorspace, default_profile, profiles in \
    ("X264_CSP_I420",  "YUV420P",    PROFILE_HIGH,      I420_PROFILES), \
    ("X264_CSP_I422",  "YUV422P",    PROFILE_HIGH422,   I422_PROFILES), \
    ("X264_CSP_I444",  "YUV444P",    PROFILE_HIGH444_PREDICTIVE,    I444_PROFILES), \
    ("X264_CSP_BGR",   "BGR",        PROFILE_HIGH444_PREDICTIVE,    RGB_PROFILES), \
    ("X264_CSP_BGRA",  "BGRA",       PROFILE_HIGH444_PREDICTIVE,    RGB_PROFILES), \
    ("X264_CSP_BGRA",  "BGRX",       PROFILE_HIGH444_PREDICTIVE,    RGB_PROFILES), \
    ("X264_CSP_RGB",   "RGB",        PROFILE_HIGH444_PREDICTIVE,    RGB_PROFILES):
    enum_val = constants.get(x264_enum)
    if enum_val is None:
        debug("enc_x264: this build does not support %s / %s", x264_enum, colorspace)
        continue
    COLORSPACES[colorspace] = (enum_val, default_profile, profiles)

#copy C list of colorspaces to a python list:
def get_colorspaces():
    global COLORSPACES
    return  COLORSPACES.keys()

def get_spec(encoding, colorspace):
    assert encoding in get_encodings(), "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES.keys())
    #ratings: quality, speed, setup cost, cpu cost, gpu cost, latency, max_w, max_h, max_pixels
    #we can handle high quality and any speed
    #setup cost is moderate (about 10ms)
    return codec_spec(Encoder, codec_type=get_type(), encoding=encoding, speed=50, setup_cost=70, width_mask=0xFFFE, height_mask=0xFFFE)


cdef class Encoder:
    cdef int frames
    cdef x264_t *context
    cdef int width
    cdef int height
    cdef object src_format
    cdef object profile
    cdef double time
    cdef int colorspace
    cdef int preset
    cdef int quality
    cdef int speed
    cdef long long bytes_in
    cdef long long bytes_out

    def init_context(self, int width, int height, src_format, encoding, int quality, int speed, options):    #@DuplicatedSignature
        global COLORSPACES
        cs_info = COLORSPACES.get(src_format)
        assert cs_info is not None, "invalid source format: %s, must be one of: %s" % (src_format, COLORSPACES.keys())
        assert encoding=="h264", "invalid encoding: %s" % encoding
        self.width = width
        self.height = height
        self.quality = quality
        self.speed = speed
        self.preset = get_preset_for_speed(speed)
        self.src_format = src_format
        self.colorspace = cs_info[0]
        self.frames = 0
        self.time = 0
        self.profile = self._get_profile(options, self.src_format)
        if self.profile is not None and self.profile not in cs_info[2]:
            log.warn("invalid profile specified for %s: %s (must be one of: %s)" % (src_format, self.profile, cs_info[2]))
            self.profile = None
        if self.profile is None:
            self.profile = cs_info[1]
        self.init_encoder()

    cdef init_encoder(self):
        cdef x264_param_t param
        cdef const char *preset
        preset = get_preset_names()[self.preset]
        x264_param_default_preset(&param, preset, "zerolatency")
        param.i_threads = X264_THREADS
        if X264_THREADS!=1:
            param.b_sliced_threads = 1
        param.i_width = self.width
        param.i_height = self.height
        param.i_csp = self.colorspace
        set_f_rf(&param, get_x264_quality(self.quality))
        param.i_log_level = constants["X264_LOG_ERROR"]
        #we never lose frames or use seeking, so no need for regular I-frames:
        param.i_keyint_max = 999999
        #we don't want IDR frames either:
        param.i_keyint_min = 999999
        param.b_intra_refresh = 0   #no intra refresh
        param.b_open_gop = 1        #allow open gop
        x264_param_apply_profile(&param, self.profile)
        self.context = x264_encoder_open(&param)
        assert self.context!=NULL,  "context initialization failed for format %s" % self.src_format

    def get_info(self):
        cdef float pps
        if self.profile is None:
            return {}
        info = {"profile"   : self.profile,
                "preset"    : get_preset_names()[self.preset],
                "frames"    : self.frames,
                "width"     : self.width,
                "height"    : self.height,
                "speed"     : self.speed,
                "quality"   : self.quality,
                "src_format": self.src_format,
                "version"   : get_version()}
        if self.bytes_in>0 and self.bytes_out>0:
            info["bytes_in"] = self.bytes_in
            info["bytes_out"] = self.bytes_out
            info["ratio_pct"] = int(100.0 * self.bytes_out / self.bytes_in)
        if self.frames>0 and self.time>0:
            pps = float(self.width) * float(self.height) * float(self.frames) / self.time
            info["total_time_ms"] = int(self.time*1000.0)
            info["pixels_per_second"] = int(pps)
        return info

    def __str__(self):
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

    def _get_profile(self, options, csc_mode):
        #try the environment as a default, fallback to hardcoded default:
        profile = os.environ.get("XPRA_X264_%s_PROFILE" % csc_mode)
        #now see if the client has requested a different value:
        profile = options.get("x264.%s.profile" % csc_mode, profile)
        if not profile:
            #also using the old names:
            old_csc_name = {"YUV420P" : "I420",
                            "YUV422P" : "I422",
                            "YUV444P" : "I444",
                            }.get(csc_mode, csc_mode)
            profile = options.get("x264.%s.profile" % csc_mode, profile)
        return profile

    def clean(self):                        #@DuplicatedSignature
        if self.context!=NULL:
            x264_encoder_close(self.context)
            self.context = NULL

    def get_client_options(self, options):
        q = options.get("quality", -1)
        if q<0:
            q = self.quality
        s = options.get("speed", -1)
        if s<0:
            s = self.speed
        return {
                "frame"     : self.frames,
                "quality"   : q,
                "speed"     : s,
                }

    def compress_image(self, image, options={}):
        cdef x264_nal_t *nals = NULL
        cdef int i_nals = 0
        cdef x264_picture_t pic_out
        cdef x264_picture_t pic_in
        cdef int frame_size = 0

        cdef uint8_t *pic_buf
        cdef Py_ssize_t pic_buf_len = 0
        cdef char *out

        cdef int quality_override = options.get("quality", -1)
        cdef int speed_override = options.get("speed", -1)
        cdef int saved_quality = self.quality
        cdef int saved_speed = self.speed
        cdef int i                        #@DuplicatedSignature
        start = time.time()

        if speed_override>=0 and saved_speed!=speed_override:
            self.set_encoding_speed(speed_override)
        if quality_override>=0 and saved_quality!=quality_override:
            self.set_encoding_quality(quality_override)
        assert self.context!=NULL
        pixels = image.get_pixels()
        istrides = image.get_rowstride()

        memset(&pic_out, 0, sizeof(x264_picture_t))
        memset(&pic_in, 0, sizeof(x264_picture_t))

        if self.src_format.find("RGB")>=0 or self.src_format.find("BGR")>=0:
            assert len(pixels)>0
            assert istrides>0
            PyObject_AsReadBuffer(pixels, <const void**> &pic_buf, &pic_buf_len)
            for i in range(3):
                pic_in.img.plane[i] = pic_buf
                pic_in.img.i_stride[i] = istrides
            self.bytes_in += pic_buf_len
        else:
            assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
            assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
            for i in range(3):
                PyObject_AsReadBuffer(pixels[i], <const void**> &pic_buf, &pic_buf_len)
                pic_in.img.plane[i] = pic_buf
                pic_in.img.i_stride[i] = istrides[i]

        pic_in.img.i_csp = self.colorspace
        pic_in.img.i_plane = 3
        pic_in.i_pts = 1

        try:
            with nogil:
                frame_size = x264_encoder_encode(self.context, &nals, &i_nals, &pic_in, &pic_out)
            if frame_size < 0:
                log.error("x264 encoding error: frame_size is invalid!")
                return None
            out = <char *>nals[0].p_payload
            cdata = out[:frame_size]
            self.bytes_out += frame_size
            end = time.time()
            self.time += end-start
            self.frames += 1
            return  cdata, self.get_client_options(options)
        finally:
            if speed_override>=0 and saved_speed!=speed_override:
                self.set_encoding_speed(saved_speed)
            if quality_override>=0 and saved_quality!=quality_override:
                self.set_encoding_quality(saved_quality)


    def set_encoding_speed(self, int pct):
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        assert self.context!=NULL, "context is closed!"
        cdef x264_param_t param                     #@DuplicatedSignature
        cdef int new_preset = get_preset_for_speed(pct)
        if new_preset == self.preset:
            return
        #retrieve current parameters:
        x264_encoder_parameters(self.context, &param)
        #apply new preset:
        x264_param_default_preset(&param, get_preset_names()[new_preset], "zerolatency")
        #ensure quality remains what it was:
        set_f_rf(&param, get_x264_quality(self.quality))
        #apply it:
        x264_param_apply_profile(&param, self.profile)
        if x264_encoder_reconfig(self.context, &param)!=0:
            raise Exception("x264_encoder_reconfig failed for speed=%s" % pct)
        self.preset = new_preset

    def set_encoding_quality(self, int pct):
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        assert self.context!=NULL, "context is closed!"
        if int(self.quality/2) == int(pct/2):
            #not enough of a change to bother
            return
        cdef x264_param_t param                  #@DuplicatedSignature
        #only f_rf_constant is changing
        #retrieve current parameters:
        x264_encoder_parameters(self.context, &param)
        #adjust quality:
        set_f_rf(&param, get_x264_quality(self.quality))
        #apply it:
        if x264_encoder_reconfig(self.context, &param)!=0:
            raise Exception("x264_encoder_reconfig failed for quality=%s" % pct)
        self.quality = pct
