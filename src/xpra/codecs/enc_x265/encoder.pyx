# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False, wraparound=False, cdivision=True
from __future__ import absolute_import

import os

from xpra.log import Logger
log = Logger("encoder", "x265")

from xpra.util import envbool
from xpra.codecs.codec_constants import get_subsampling_divs, RGB_FORMATS, video_spec
from xpra.buffers.membuf cimport object_as_buffer

from libc.stdint cimport int64_t, uint64_t, uint8_t, uint32_t, uintptr_t
from xpra.monotonic_time cimport monotonic_time


LOG_NALS = envbool("XPRA_X265_LOG_NALS", False)


cdef extern from "stdint.h":
    pass
cdef extern from "inttypes.h":
    pass


cdef extern from "x265.h":

    const char *x265_version_str
    int x265_max_bit_depth

    int NAL_UNIT_CODED_SLICE_TRAIL_N
    int NAL_UNIT_CODED_SLICE_TRAIL_R
    int NAL_UNIT_CODED_SLICE_TSA_N
    int NAL_UNIT_CODED_SLICE_TLA_R
    int NAL_UNIT_CODED_SLICE_STSA_N
    int NAL_UNIT_CODED_SLICE_STSA_R
    int NAL_UNIT_CODED_SLICE_RADL_N
    int NAL_UNIT_CODED_SLICE_RADL_R
    int NAL_UNIT_CODED_SLICE_RASL_N
    int NAL_UNIT_CODED_SLICE_RASL_R
    int NAL_UNIT_CODED_SLICE_BLA_W_LP
    int NAL_UNIT_CODED_SLICE_BLA_W_RADL
    int NAL_UNIT_CODED_SLICE_BLA_N_LP
    int NAL_UNIT_CODED_SLICE_IDR_W_RADL
    int NAL_UNIT_CODED_SLICE_IDR_N_LP
    int NAL_UNIT_CODED_SLICE_CRA
    int NAL_UNIT_VPS
    int NAL_UNIT_SPS
    int NAL_UNIT_PPS
    int NAL_UNIT_ACCESS_UNIT_DELIMITER
    int NAL_UNIT_EOS
    int NAL_UNIT_EOB
    int NAL_UNIT_FILLER_DATA
    int NAL_UNIT_PREFIX_SEI
    int NAL_UNIT_SUFFIX_SEI
    int NAL_UNIT_INVALID

    ctypedef struct rc:
        int         rateControlMode                 #explicit mode of rate-control, must be one of the X265_RC_METHODS enum values
        int         qp                              #base QP to use for Constant QP rate control
        int         bitrate                         #target bitrate for Average BitRate
        double      rateTolerance                   #the degree of rate fluctuation that x265 tolerates
        double      qCompress                       #sets the quantizer curve compression factor
        double      ipFactor
        double      pbFactor
        int         qpStep                          #Max QP difference between frames
        double      rfConstant
        int         aqMode                          #enable adaptive quantization
        double      aqStrength                      #sets the strength of AQ bias towards low detail macroblocks
        int         vbvMaxBitrate                   #sets the maximum rate the VBV buffer should be assumed to refill at
        int         vbvBufferSize                   #sets the size of the VBV buffer in kilobits. Default is zero
        double      vbvBufferInit                   #sets how full the VBV buffer must be before playback starts
        int         cuTree                          #enable CUTree ratecontrol
        double      rfConstantMax                   #in CRF mode, maximum CRF as caused by VBV

    ctypedef struct x265_param:
        int         logLevel
        const char  *csvfn
        int         bEnableWavefront                #enable wavefront parallel processing
        int         poolNumThreads                  #number of threads to allocate for thread pool
        int         frameNumThreads                 #number of concurrently encoded frames

        int         sourceWidth                     #source width in pixels
        int         sourceHeight                    #source height in pixels
        int         internalBitDepth                #Internal encoder bit depth
        int         internalCsp                     #color space of internal pictures


        int         fpsNum                          #framerate numerator
        int         fpsDenom                        #framerate denominator

        uint32_t    tuQTMaxInterDepth               #1 (speed) to 3 (efficient)
        uint32_t    tuQTMaxIntraDepth               #1 (speed) to 3 (efficient)
        int         bOpenGOP                        #Enable Open GOP referencing
        int         keyframeMin                     #Minimum intra period in frames
        int         keyframeMax                     #Maximum intra period in frames
        int         maxNumReferences                #1 (speed) to 16 (efficient)
        int         bframes                         #Max number of consecutive B-frames
        int         bBPyramid                       #use some B frames as a motion reference for the surrounding B frames
        int         lookaheadDepth                  #Number of frames to use for lookahead, determines encoder latency
        int         lookaheadSlices                 #Use multiple worker threads to measure the estimated cost of each frame within the lookahead
        int         bFrameAdaptive                  #0 - none, 1 - fast, 2 - full (trellis) adaptive B frame scheduling
        int         bFrameBias                      #value which is added to the cost estimate of B frames
        int         scenecutThreshold               #how aggressively to insert extra I frames
        int         bEnableConstrainedIntra         #enable constrained intra prediction
        int         bEnableStrongIntraSmoothing     #enable strong intra smoothing for 32x32 blocks where the reference samples are flat

        int         searchMethod                    #ME search method (DIA, HEX, UMH, STAR, FULL)
        int         subpelRefine                    #amount of effort performed during subpel refine
        int         searchRange                     #ME search range
        uint32_t    maxNumMergeCand                 #Max number of merge candidates
        int         bEnableWeightedPred             #enable weighted prediction in P slices
        int         bEnableWeightedBiPred           #enable bi-directional weighted prediction in B slices
        int         bEnableAMP                      #enable asymmetrical motion predictions
        int         bEnableRectInter                #enable rectangular motion prediction partitions
        int         bEnableCbfFastMode              #enable the use of `coded block flags`
        int         bEnableEarlySkip                #enable early skip decisions
        int         rdPenalty                       #penalty to the estimated cost of 32x32 intra blocks in non-intra slices (0 to 2)
        int         rdLevel                         #level of rate distortion optimizations to perform (0-fast, X265_RDO_LEVEL-efficient)
        int         bEnableSignHiding               #enable the implicit signaling of the sign bit of the last coefficient of each transform unit
        int         bEnableTransformSkip            #allow intra coded blocks to be encoded directly as residual
        int         bEnableTSkipFast                #enable a faster determination of whether skippig the DCT transform will be beneficial
        int         bEnableLoopFilter               #enable the deblocking loop filter
        int         bEnableSAO                      #enable the Sample Adaptive Offset loop filter
        int         saoLcuBoundary                  #select the method in which SAO deals with deblocking boundary pixels
        int         saoLcuBasedOptimization         #select the scope of the SAO optimization
        int         cbQpOffset                      #small signed integer which offsets the QP used to quantize the Cb chroma residual
        int         crQpOffset                      #small signed integer which offsets the QP used to quantize the Cr chroma residual

        rc          rc


    ctypedef struct x265_encoder:
        pass
    ctypedef struct x265_picture:
        void        *planes[3]
        int         stride[3]
        int         bitDepth
        int         sliceType
        int         poc
        int         colorSpace
        int64_t     pts
        int64_t     dts
        void        *userData

    ctypedef struct x265_nal:
        uint32_t    type                            #NalUnitType
        uint32_t    sizeBytes                       #size in bytes
        uint8_t*    payload

    ctypedef struct x265_stats:
        double    globalPsnrY
        double    globalPsnrU
        double    globalPsnrV
        double    globalPsnr
        double    globalSsim
        double    elapsedEncodeTime                 # wall time since encoder was opened
        double    elapsedVideoTime                  # encoded picture count / frame rate
        double    bitrate                           # accBits / elapsed video time
        uint32_t  encodedPictureCount               # number of output pictures thus far
        uint32_t  totalWPFrames                     # number of uni-directional weighted frames used
        uint64_t  accBits                           # total bits output thus far

    #X265_ME_METHODS:
    int X265_DIA_SEARCH,
    int X265_HEX_SEARCH
    int X265_UMH_SEARCH
    int X265_STAR_SEARCH
    int X265_FULL_SEARCH

    int X265_LOG_NONE
    int X265_LOG_ERROR
    int X265_LOG_WARNING
    int X265_LOG_INFO
    int X265_LOG_DEBUG

    #frame type:
    int X265_TYPE_AUTO                              # Let x265 choose the right type
    int X265_TYPE_IDR
    int X265_TYPE_I
    int X265_TYPE_P
    int X265_TYPE_BREF                              # Non-disposable B-frame
    int X265_TYPE_B

    #input formats defined (only I420 and I444 are supported)
    int X265_CSP_I400                               # yuv 4:0:0 planar
    int X265_CSP_I420                               # yuv 4:2:0 planar
    int X265_CSP_I422                               # yuv 4:2:2 planar
    int X265_CSP_I444                               # yuv 4:4:4 planar
    int X265_CSP_NV12                               # yuv 4:2:0, with one y plane and one packed u+v
    int X265_CSP_NV16                               # yuv 4:2:2, with one y plane and one packed u+v
    int X265_CSP_BGR                                # packed bgr 24bits
    int X265_CSP_BGRA                               # packed bgr 32bits
    int X265_CSP_RGB                                # packed rgb 24bits

    #rate tolerance:
    int X265_RC_ABR
    int X265_RC_CQP
    int X265_RC_CRF

    x265_param *x265_param_alloc()
    void x265_param_free(x265_param *)
    void x265_param_default(x265_param *param)

    x265_encoder *x265_encoder_open(x265_param *)
    void x265_encoder_close(x265_encoder *encoder)
    void x265_cleanup()

    #static const char * const x265_profile_names[] = { "main", "main10", "mainstillpicture", 0 };
    #static const char * const x265_preset_names[] = { "ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow", "placebo", 0 };
    #static const char * const x265_tune_names[] = { "psnr", "ssim", "zero-latency", 0 };

    int x265_param_apply_profile(x265_param *param, const char *profile)
    int x265_param_default_preset(x265_param *param, const char *preset, const char *tune)

    x265_picture *x265_picture_alloc()
    void x265_picture_free(x265_picture *pic)
    void x265_picture_init(x265_param *param, x265_picture *pic)

    int x265_encoder_headers(x265_encoder *encoder, x265_nal **pp_nal, uint32_t *pi_nal) nogil
    int x265_encoder_encode(x265_encoder *encoder, x265_nal **pp_nal, uint32_t *pi_nal, x265_picture *pic_in, x265_picture *pic_out) nogil

cdef char *PROFILE_MAIN     = "main"
cdef char *PROFILE_MAIN10   = "main10"
cdef char *PROFILE_MAINSTILLPICTURE = "mainstillpicture"
PROFILES = [PROFILE_MAIN, PROFILE_MAIN10, PROFILE_MAINSTILLPICTURE]

NAL_TYPES = {
    NAL_UNIT_CODED_SLICE_TRAIL_N        : "CODED_SLICE_TRAIL_N",
    NAL_UNIT_CODED_SLICE_TRAIL_R        : "CODED_SLICE_TRAIL_R",
    NAL_UNIT_CODED_SLICE_TSA_N          : "CODED_SLICE_TSA_N",
    NAL_UNIT_CODED_SLICE_TLA_R          : "CODED_SLICE_TLA_R",
    NAL_UNIT_CODED_SLICE_STSA_N         : "CODED_SLICE_STSA_N",
    NAL_UNIT_CODED_SLICE_STSA_R         : "CODED_SLICE_STSA_R",
    NAL_UNIT_CODED_SLICE_RADL_N         : "CODED_SLICE_RADL_N",
    NAL_UNIT_CODED_SLICE_RADL_R         : "CODED_SLICE_RADL_R",
    NAL_UNIT_CODED_SLICE_RASL_N         : "CODED_SLICE_RASL_N",
    NAL_UNIT_CODED_SLICE_RASL_R         : "CODED_SLICE_RASL_R",
    NAL_UNIT_CODED_SLICE_BLA_W_LP       : "CODED_SLICE_BLA_W_LP",
    NAL_UNIT_CODED_SLICE_BLA_W_RADL     : "CODED_SLICE_BLA_W_RADL",
    NAL_UNIT_CODED_SLICE_BLA_N_LP       : "CODED_SLICE_BLA_N_LP",
    NAL_UNIT_CODED_SLICE_IDR_W_RADL     : "CODED_SLICE_IDR_W_RADL",
    NAL_UNIT_CODED_SLICE_IDR_N_LP       : "CODED_SLICE_IDR_N_LP",
    NAL_UNIT_CODED_SLICE_CRA            : "CODED_SLICE_CRA",
    NAL_UNIT_VPS                        : "VPS",
    NAL_UNIT_SPS                        : "SPS",
    NAL_UNIT_PPS                        : "PPS",
    NAL_UNIT_ACCESS_UNIT_DELIMITER      : "ACCESS_UNIT_DELIMITER",
    NAL_UNIT_EOS                        : "EOS",
    NAL_UNIT_EOB                        : "EOB",
    NAL_UNIT_FILLER_DATA                : "FILLER_DATA",
    NAL_UNIT_PREFIX_SEI                 : "PREFIX_SEI",
    NAL_UNIT_SUFFIX_SEI                 : "SUFFIX_SEI",
    NAL_UNIT_INVALID                    : "INVALID",
    }

#as per the source code: only these two formats are supported:
COLORSPACES = ["YUV420P", "YUV444P"]


def init_module():
    log("enc_x265.init_module()")

def cleanup_module():
    log("enc_x265.cleanup_module()")

def get_version():
    return x265_version_str

def get_type():
    return "x265"

def get_info():
    f = {}
    for e in get_encodings():
        f["formats.%s" % e] = get_input_colorspaces(e)
    return  {
             "version"      : get_version(),
             "encodings"    : get_encodings(),
             "formats"      : f,
             }

def get_encodings():
    return ["h265"]

def get_input_colorspaces(encoding):
    assert encoding in get_encodings()
    return COLORSPACES

def get_output_colorspaces(encoding, input_colorspace):
    assert encoding in get_encodings()
    assert input_colorspace in COLORSPACES
    return (input_colorspace, )


def get_spec(encoding, colorspace):
    assert encoding in get_encodings(), "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES.keys())
    #ratings: quality, speed, setup cost, cpu cost, gpu cost, latency, max_w, max_h, max_pixels
    #we can handle high quality and any speed
    #setup cost is moderate (about 10ms)
    return video_spec(encoding=encoding, output_colorspaces=[colorspace],
                      codec_class=Encoder, codec_type=get_type(),
                      min_w=64, min_h=64,
                      setup_cost=70, width_mask=0xFFFE, height_mask=0xFFFE)


if envbool("XPRA_X265_DEBUG", False):
    log_level = X265_LOG_INFO
else:
    log_level = X265_LOG_WARNING


cdef class Encoder:
    cdef x265_param *param
    cdef x265_encoder *context
    cdef int width
    cdef int height
    cdef object src_format
    cdef object preset
    cdef char *profile
    cdef int quality
    cdef int speed
    cdef double time
    cdef unsigned long frames
    cdef int64_t first_frame_timestamp

    cdef object __weakref__

    def init_context(self, int width, int height, src_format, dst_formats, encoding, int quality, int speed, scaling, options):    #@DuplicatedSignature
        global COLORSPACES
        assert src_format in COLORSPACES, "invalid source format: %s, must be one of: %s" % (src_format, COLORSPACES)
        assert encoding=="h265", "invalid encoding: %s" % encoding
        self.width = width
        self.height = height
        self.quality = quality
        self.speed = speed
        self.src_format = src_format
        self.frames = 0
        self.time = 0
        self.preset = b"ultrafast"
        self.profile = PROFILE_MAIN
        self.init_encoder()

    cdef init_encoder(self):
        global log_level
        cdef const char *preset

        self.param = x265_param_alloc()
        assert self.param!=NULL
        x265_param_default(self.param)
        if x265_param_apply_profile(self.param, self.profile)!=0:
            raise Exception("failed to set profile: %s" % self.profile)
        if x265_param_default_preset(self.param, self.preset, b"zero-latency")!=0:
            raise Exception("failed to set preset: %s" % self.preset)

        self.param.sourceWidth = self.width
        self.param.sourceHeight = self.height
        self.param.frameNumThreads = 1
        self.param.logLevel = log_level
        self.param.bOpenGOP = 1
        self.param.searchMethod = X265_HEX_SEARCH
        self.param.fpsNum = 1
        self.param.fpsDenom = 1
        #force zero latency:
        self.param.bframes = 0
        self.param.bFrameAdaptive = 0
        self.param.lookaheadDepth = 0
        if self.height<720 or self.width<1024:
            self.param.lookaheadSlices = 0
        if False:
            #unused settings:
            self.param.internalBitDepth = 8
            self.param.searchRange = 30
            self.param.keyframeMin = 0
            self.param.keyframeMax = -1
            self.param.tuQTMaxInterDepth = 2
            self.param.tuQTMaxIntraDepth = 2
            self.param.maxNumReferences = 1
            self.param.bBPyramid = 0
            self.param.bFrameBias = 0
            self.param.scenecutThreshold = 40
            self.param.bEnableConstrainedIntra = 0
            self.param.bEnableStrongIntraSmoothing = 1
            self.param.maxNumMergeCand = 2
            self.param.subpelRefine = 5
            self.param.bEnableWeightedPred = 0
            self.param.bEnableWeightedBiPred = 0
            self.param.bEnableAMP = 0
            self.param.bEnableRectInter = 1
            self.param.bEnableCbfFastMode = 1
            self.param.bEnableEarlySkip = 1
            self.param.rdPenalty = 2
            self.param.rdLevel = 0
            self.param.bEnableSignHiding = 0
            self.param.bEnableTransformSkip = 0
            self.param.bEnableTSkipFast = 1
            self.param.bEnableLoopFilter = 0
            self.param.bEnableSAO = 0
            self.param.saoLcuBoundary = 0
            self.param.saoLcuBasedOptimization = 0
            self.param.cbQpOffset = 0
            self.param.crQpOffset = 0

        self.param.rc.bitrate = 5000
        self.param.rc.rateControlMode = X265_RC_ABR

        if self.src_format=="YUV420P":
            self.param.internalCsp = X265_CSP_I420
        else:
            assert self.src_format=="YUV444P"
            self.param.internalCsp = X265_CSP_I444
        self.context = x265_encoder_open(self.param)
        log("init_encoder() x265 context=%#x", <uintptr_t> self.context)
        assert self.context!=NULL,  "context initialization failed for format %s and size %ix%i" % (self.src_format, self.width, self.height)

    def clean(self):                        #@DuplicatedSignature
        log("clean() x265 param=%#x, context=%#x", <uintptr_t> self.param, <uintptr_t> self.context)
        if self.param!=NULL:
            x265_param_free(self.param)
            self.param = NULL
        if self.context!=NULL:
            x265_encoder_close(self.context)
            self.context = NULL
        self.width = 0
        self.height = 0
        self.src_format = ""
        self.preset = None
        self.profile = ""
        self.quality = 0
        self.speed = 0
        self.time = 0
        self.frames = 0
        self.first_frame_timestamp = 0


    def get_info(self):             #@DuplicatedSignature
        cdef float pps
        if self.profile is None:
            return {}
        info = {
            "profile"   : self.profile,
            #"preset"    : get_preset_names()[self.preset],
            "frames"    : int(self.frames),
            "width"     : self.width,
            "height"    : self.height,
            "speed"     : self.speed,
            "quality"   : self.quality,
            "src_format": self.src_format,
            }
        if self.frames>0 and self.time>0:
            pps = float(self.width) * float(self.height) * float(self.frames) / self.time
            info["total_time_ms"] = int(self.time*1000.0)
            info["pixels_per_second"] = int(pps)
        return info

    def __repr__(self):
        if self.src_format is None:
            return "x264_encoder(uninitialized)"
        return "x264_encoder(%s - %sx%s)" % (self.src_format, self.width, self.height)

    def is_closed(self):
        return self.context==NULL

    def get_encoding(self):
        return "h265"

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):                     #@DuplicatedSignature
        return  "x265"

    def get_src_format(self):
        return self.src_format


    def compress_image(self, image, quality=-1, speed=-1, options={}):
        cdef x265_nal *nal
        cdef uint32_t nnal = 0
        cdef unsigned int i                        #@DuplicatedSignature
        cdef int r = 0
        cdef x265_picture *pic_out = NULL
        cdef x265_picture *pic_in = NULL
        cdef int nal_size, frame_size = 0

        cdef uint8_t *pic_buf
        cdef Py_ssize_t pic_buf_len = 0
        cdef char *out

        assert self.context!=NULL
        pixels = image.get_pixels()
        istrides = image.get_rowstride()
        assert image.get_pixel_format()==self.src_format, "invalid input format %s, expected %s" % (image.get_pixel_format, self.src_format)
        assert image.get_width()==self.width and image.get_height()==self.height
        assert pixels, "failed to get pixels from %s" % image
        assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
        assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)

        cdef double start = monotonic_time()
        data = []
        log("x265.compress_image(%s, %s)", image, options)
        if self.frames==0:
            #first frame, record pts:
            self.first_frame_timestamp = image.get_timestamp()
            #send headers (not needed?)
            if x265_encoder_headers(self.context, &nal, &nnal)<0:
                log.error("x265 encoding headers error: %s", r)
                return None
            log("x265 header nals: %s", nnal)
            for i in range(nnal):
                out = <char *>nal[i].payload
                data.append(out[:nal[i].sizeBytes])
                log("x265 header[%s]: %s bytes", i, nal[i].sizeBytes)

        pic_out = x265_picture_alloc()
        assert pic_out!=NULL, "failed to allocate output picture"
        try:
            pic_in = x265_picture_alloc()
            assert pic_in!=NULL, "failed to allocate input picture"
            try:
                x265_picture_init(self.param, pic_in)
                assert pixels, "failed to get pixels from %s" % image
                assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
                assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
                for i in range(3):
                    assert object_as_buffer(pixels[i], <const void**> &pic_buf, &pic_buf_len)==0
                    pic_in.planes[i] = pic_buf
                    pic_in.stride[i] = istrides[i]
                pic_in.pts = image.get_timestamp()-self.first_frame_timestamp
                with nogil:
                    r = x265_encoder_encode(self.context, &nal, &nnal, pic_in, pic_out)
                log("x265 picture encode returned %s (nnal=%s)", r, nnal)
                if r==0:
                    r = x265_encoder_encode(self.context, &nal, &nnal, NULL, pic_out)
                    log("x265 picture encode returned %s (nnal=%s)", r, nnal)
            finally:
                x265_picture_free(pic_in)
            if r<=0:
                log.error("Error: x265 encoder returned %i", r)
                return None
            #copy nals:
            for i in range(nnal):
                nal_size = nal[i].sizeBytes
                out = <char *>nal[i].payload
                if LOG_NALS:
                    log.info(" nal %s type:%10s, payload=%#x, payload size=%#x",
                             i, NAL_TYPES.get(nal[i].type, nal[i].type), <uintptr_t> out, nal_size)
                frame_size += nal_size
                data.append(out[:nal_size])
        finally:
            x265_picture_free(pic_out)
        client_options = {
                "frame"     : self.frames,
                "pts"     : image.get_timestamp()-self.first_frame_timestamp,
                }
        cdef double end = monotonic_time()
        self.time += end-start
        self.frames += 1
        log("x265 compressed data size: %s, client options=%s", frame_size, client_options)
        return  b"".join(data), client_options


def selftest(full=False):
    from xpra.codecs.codec_checks import testencoder
    from xpra.codecs.enc_x265 import encoder
    global log_level
    saved = log_level
    try:
        log_level = X265_LOG_ERROR
        assert testencoder(encoder, full)
    finally:
        log_level = saved
