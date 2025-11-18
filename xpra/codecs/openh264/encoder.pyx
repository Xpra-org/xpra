# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import os
from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.log import Logger
log = Logger("encoder", "openh264")

from xpra.codecs.image import ImageWrapper
from xpra.util.str_fn import csv
from xpra.util.objects import typedict, AtomicInteger
from xpra.codecs.constants import VideoSpec
from collections import deque

from libcpp cimport bool as bool_t
from libc.string cimport memset
from libc.stdint cimport uint8_t, uintptr_t


SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")

DEF MAX_SPATIAL_LAYER_NUM = 4
DEF MAX_LAYER_NUM_OF_FRAME = 128

cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "wels/codec_app_def.h":
    int VIDEO_BITSTREAM_AVC
    int VIDEO_BITSTREAM_SVC
    int VIDEO_BITSTREAM_DEFAULT
    ctypedef struct OpenH264Version:
        unsigned int uMajor
        unsigned int uMinor
        unsigned int uRevision
        unsigned int uReserved

    ctypedef enum ENCODER_OPTION:
        ENCODER_OPTION_DATAFORMAT
        ENCODER_OPTION_IDR_INTERVAL             #IDR period,0/-1 means no Intra period (only the first frame) lager than 0 means the desired IDR period, must be multiple of (2^temporal_layer)
        ENCODER_OPTION_SVC_ENCODE_PARAM_BASE    #structure of Base Param
        ENCODER_OPTION_SVC_ENCODE_PARAM_EXT     #structure of Extension Param
        ENCODER_OPTION_FRAME_RATE               #maximal input frame rate, current supported range: MAX_FRAME_RATE = 30,MIN_FRAME_RATE = 1
        ENCODER_OPTION_BITRATE
        ENCODER_OPTION_MAX_BITRATE
        ENCODER_OPTION_INTER_SPATIAL_PRED
        ENCODER_OPTION_RC_MODE
        ENCODER_OPTION_RC_FRAME_SKIP
        ENCODER_PADDING_PADDING                 #0:disable padding;1:padding

        ENCODER_OPTION_PROFILE                  #assign the profile for each layer
        ENCODER_OPTION_LEVEL                    #assign the level for each layer
        ENCODER_OPTION_NUMBER_REF               #the number of reference frame
        ENCODER_OPTION_DELIVERY_STATUS          #the delivery info which is a feedback from app level

        ENCODER_LTR_RECOVERY_REQUEST
        ENCODER_LTR_MARKING_FEEDBACK
        ENCODER_LTR_MARKING_PERIOD
        ENCODER_OPTION_LTR                      #0:disable LTR;larger than 0 enable LTR; LTR number is fixed to be 2 in current encoder
        ENCODER_OPTION_COMPLEXITY

        ENCODER_OPTION_ENABLE_SSEI              #enable SSEI: true--enable ssei; false--disable ssei
        ENCODER_OPTION_ENABLE_PREFIX_NAL_ADDING #enable prefix: true--enable prefix; false--disable prefix
        ENCODER_OPTION_SPS_PPS_ID_STRATEGY      #different strategy in adjust ID in SPS/PPS: 0- constant ID, 1-additional ID, 6-mapping and additional

        ENCODER_OPTION_CURRENT_PATH
        ENCODER_OPTION_DUMP_FILE                #dump layer reconstruct frame to a specified file
        ENCODER_OPTION_TRACE_LEVEL              #trace info based on the trace level
        ENCODER_OPTION_TRACE_CALLBACK           #a void (*)(void* context, int level, const char* message) function which receives log messages
        ENCODER_OPTION_TRACE_CALLBACK_CONTEXT   #context info of trace callback

        ENCODER_OPTION_GET_STATISTICS           #read only
        ENCODER_OPTION_STATISTICS_LOG_INTERVAL  #log interval in millisecond

        ENCODER_OPTION_IS_LOSSLESS_LINK         #advanced algorithmetic settings

        ENCODER_OPTION_BITS_VARY_PERCENTAGE     #bit vary percentage

    ctypedef enum EProfileIdc:
        PRO_UNKNOWN
        PRO_BASELINE
        PRO_MAIN
        PRO_EXTENDED
        PRO_HIGH
        PRO_HIGH10
        PRO_HIGH422
        PRO_HIGH444
        PRO_CAVLC444
        PRO_SCALABLE_BASELINE
        PRO_SCALABLE_HIGH

    ctypedef enum ELevelIdc:
        LEVEL_UNKNOWN
        LEVEL_1_0
        LEVEL_1_B
        LEVEL_1_1
        LEVEL_1_2
        LEVEL_1_3
        LEVEL_2_0
        LEVEL_2_1
        LEVEL_2_2
        LEVEL_3_0
        LEVEL_3_1
        LEVEL_3_2
        LEVEL_4_0
        LEVEL_4_1
        LEVEL_4_2
        LEVEL_5_0
        LEVEL_5_1
        LEVEL_5_2

    ctypedef enum RC_MODES:
        RC_QUALITY_MODE         #quality mode
        RC_BITRATE_MODE         #bitrate mode
        RC_BUFFERBASED_MODE     #no bitrate control,only using buffer status,adjust the video quality
        RC_TIMESTAMP_MODE       #rate control based timestamp
        RC_BITRATE_MODE_POST_SKIP   #this is in-building RC MODE, WILL BE DELETED after algorithm tuning!
        RC_OFF_MODE             #rate control off mode

    ctypedef enum EUsageType:
        CAMERA_VIDEO_REAL_TIME      #camera video for real-time communication
        SCREEN_CONTENT_REAL_TIME    #screen content signal
        CAMERA_VIDEO_NON_REAL_TIME
        SCREEN_CONTENT_NON_REAL_TIME,
        INPUT_CONTENT_TYPE_ALL

    ctypedef enum EColorPrimaries:
        CP_RESERVED0
        CP_BT709
        CP_UNDEF
        CP_RESERVED3
        CP_BT470M
        CP_BT470BG
        CP_SMPTE170M
        CP_SMPTE240M
        CP_FILM
        CP_BT2020
        CP_NUM_ENUM

    ctypedef enum ETransferCharacteristics:
        TRC_RESERVED0
        TRC_BT709
        TRC_UNDEF
        TRC_RESERVED3
        TRC_BT470M
        TRC_BT470BG
        TRC_SMPTE170M
        TRC_SMPTE240M
        TRC_LINEAR
        TRC_LOG100
        TRC_LOG316
        TRC_IEC61966_2_4
        TRC_BT1361E
        TRC_IEC61966_2_1
        TRC_BT2020_10
        TRC_BT2020_12
        TRC_NUM_ENUM

    ctypedef enum EColorMatrix:
        CM_GBR
        CM_BT709
        CM_UNDEF
        CM_RESERVED3
        CM_FCC
        CM_BT470BG
        CM_SMPTE170M
        CM_SMPTE240M
        CM_YCGCO
        CM_BT2020NC
        CM_BT2020C
        CM_NUM_ENUM

    ctypedef struct SEncParamBase:
        EUsageType  iUsageType      #application type; please refer to the definition of EUsageType
        int       iPicWidth         #width of picture in luminance samples (the maximum of all layers if multiple spatial layers presents)
        int       iPicHeight        #height of picture in luminance samples((the maximum of all layers if multiple spatial layers presents)
        int       iTargetBitrate    #target bitrate desired, in unit of bps
        RC_MODES  iRCMode           #rate control mode
        float     fMaxFrameRate     #maximal input frame rate

    ctypedef struct SSpatialLayerConfig:
        int   iVideoWidth           # width of picture in luminance samples of a layer
        int   iVideoHeight          # height of picture in luminance samples of a layer
        float fFrameRate            # frame rate specified for a layer
        int   iSpatialBitrate       # target bitrate for a spatial layer, in unit of bps
        int   iMaxSpatialBitrate    # maximum  bitrate for a spatial layer, in unit of bps
        EProfileIdc  uiProfileIdc   # value of profile IDC (PRO_UNKNOWN for auto-detection)
        ELevelIdc    uiLevelIdc     # value of profile IDC (0 for auto-detection)
        int          iDLayerQp      # value of level IDC (0 for auto-detection)

        # SSliceArgument sSliceArgument

        # Note: members bVideoSignalTypePresent through uiColorMatrix below are also defined in SWelsSPS in parameter_sets.h.
        bool_t      bVideoSignalTypePresent       # false => do not write any of the following information to the header
        unsigned char uiVideoFormat             # EVideoFormatSPS; 3 bits in header; 0-5 => component, kpal, ntsc, secam, mac, undef
        bool_t      bFullRange                    # false => analog video data range [16, 235]; true => full data range [0,255]
        bool_t      bColorDescriptionPresent      # false => do not write any of the following three items to the header
        unsigned char uiColorPrimaries          # EColorPrimaries; 8 bits in header; 0 - 9 => ???, bt709, undef, ???, bt470m, bt470bg,
                                                # smpte170m, smpte240m, film, bt2020
        unsigned char uiTransferCharacteristics # ETransferCharacteristics; 8 bits in header; 0 - 15 => ???, bt709, undef, ???, bt470m, bt470bg, smpte170m,
                                                # smpte240m, linear, log100, log316, iec61966-2-4, bt1361e, iec61966-2-1, bt2020-10, bt2020-12
        unsigned char uiColorMatrix             # EColorMatrix; 8 bits in header (corresponds to FFmpeg "colorspace"); 0 - 10 => GBR, bt709,
                                                # undef, ???, fcc, bt470bg, smpte170m, smpte240m, YCgCo, bt2020nc, bt2020c
        bool_t bAspectRatioPresent                # aspect ratio present in VUI
        # ESampleAspectRatio eAspectRatio         # aspect ratio idc
        unsigned short sAspectRatioExtWidth     # use if aspect ratio idc == 255
        unsigned short sAspectRatioExtHeight    # use if aspect ratio idc == 255

    ctypedef struct SEncParamExt:
        EUsageType iUsageType               # same as in TagEncParamBase
        int       iPicWidth                 # same as in TagEncParamBase
        int       iPicHeight                # same as in TagEncParamBase
        int       iTargetBitrate            # same as in TagEncParamBase
        RC_MODES  iRCMode                   # same as in TagEncParamBase
        float     fMaxFrameRate             # same as in TagEncParamBase

        int       iTemporalLayerNum         # temporal layer number, max temporal layer = 4
        int       iSpatialLayerNum          # spatial layer number,1<= iSpatialLayerNum <= MAX_SPATIAL_LAYER_NUM, MAX_SPATIAL_LAYER_NUM = 4
        SSpatialLayerConfig sSpatialLayers[MAX_SPATIAL_LAYER_NUM]

        # ECOMPLEXITY_MODE iComplexityMode
        unsigned int      uiIntraPeriod     # period of Intra frame
        int               iNumRefFrame      # number of reference frame used
        # EParameterSetStrategy eSpsPpsIdStrategy     # different stategy in adjust ID in SPS/PPS: 0- constant ID, 1-additional ID, 6-mapping and additional
        bool_t    bPrefixNalAddingCtrl        # false:not use Prefix NAL; true: use Prefix NAL
        bool_t    bEnableSSEI                 # false:not use SSEI; true: use SSEI
        bool_t    bSimulcastAVC               # (when encoding more than 1 spatial layer) false: use SVC syntax for higher layers; true: use Simulcast AVC
        int     iPaddingFlag                # 0:disable padding;1:padding
        int     iEntropyCodingModeFlag      # 0:CAVLC  1:CABAC.

        # rc control
        bool_t    bEnableFrameSkip            # False: don't skip frame even if VBV buffer overflow.True: allow skipping frames to keep the bitrate within limits
        int     iMaxBitrate                 # the maximum bitrate, in unit of bps, set it to UNSPECIFIED_BIT_RATE if not needed
        int     iMaxQp                      # the maximum QP encoder supports
        int     iMinQp                      # the minmum QP encoder supports
        unsigned int uiMaxNalSize           # the maximum NAL size.  This value should be not 0 for dynamic slice mode

        # LTR settings
        bool_t     bEnableLongTermReference   # 1: on, 0: off
        int      iLTRRefNum                 # the number of LTR(long term reference)
        unsigned int      iLtrMarkPeriod    # the LTR marked period that is used in feedback.
        # multi-thread settings
        unsigned short iMultipleThreadIdc   # 1 # 0: auto(dynamic imp. internal encoder); 1: multiple threads imp. disabled; lager than 1: count number of threads;
        bool_t  bUseLoadBalancing             # only used when uiSliceMode=1 or 3, will change slicing of a picture during the run-time of multi-thread encoding, so the result of each run may be different

        # Deblocking loop filter
        int       iLoopFilterDisableIdc     # 0: on, 1: off, 2: on except for slice boundaries
        int       iLoopFilterAlphaC0Offset  # AlphaOffset: valid range [-6, 6], default 0
        int       iLoopFilterBetaOffset     # BetaOffset: valid range [-6, 6], default 0

        # pre-processing feature
        bool_t    bEnableDenoise              # denoise control
        bool_t    bEnableBackgroundDetection  # background detection control //VAA_BACKGROUND_DETECTION //BGD cmd
        bool_t    bEnableAdaptiveQuant        # adaptive quantization control
        bool_t    bEnableFrameCroppingFlag    # enable frame cropping flag: TRUE always in application
        bool_t    bEnableSceneChangeDetect

        bool_t    bIsLosslessLink             # LTR advanced setting
        bool_t    bFixRCOverShoot             # fix rate control overshooting
        int     iIdrBitrateRatio            # the target bits of IDR is (idr_bitrate_ratio/100) * average target bit per frame.

    ctypedef struct SLayerBSInfo:
        unsigned char uiTemporalId
        unsigned char uiSpatialId
        unsigned char uiQualityId
        EVideoFrameType eFrameType
        unsigned char uiLayerType
        int   iSubSeqId             #refer to D.2.11 Sub-sequence information SEI message semantics
        int   iNalCount             #count number of NAL coded already
        int*  pNalLengthInByte      #length of NAL size in byte from 0 to iNalCount-1
        unsigned char*  pBsBuf      #buffer of bitstream contained

    ctypedef struct SFrameBSInfo:
        int           iLayerNum
        SLayerBSInfo  sLayerInfo[MAX_LAYER_NUM_OF_FRAME]
        EVideoFrameType eFrameType
        int iFrameSizeInBytes
        long long uiTimeStamp

    ctypedef struct SSourcePicture:
        int       iColorFormat      #color space type
        int       iStride[4]        #stride for each plane pData
        unsigned char*  pData[4]    #plane pData
        int       iPicWidth         #luma picture width in x coordinate
        int       iPicHeight        #luma picture height in y coordinate
        long long uiTimeStamp       #timestamp of the source picture, unit: millisecond

    ctypedef enum WELS_LOG:
        WELS_LOG_QUIET              #quiet mode
        WELS_LOG_ERROR              #error log iLevel
        WELS_LOG_WARNING            #Warning log iLevel
        WELS_LOG_INFO               #information log iLevel
        WELS_LOG_DEBUG              #debug log, critical algo log
        WELS_LOG_DETAIL             #per packet/frame log
        WELS_LOG_RESV               #resversed log iLevel
        WELS_LOG_LEVEL_COUNT
        WELS_LOG_DEFAULT

cdef extern from "wels/codec_def.h":
    ctypedef enum EVideoFrameType:
        videoFrameTypeInvalid   #encoder not ready or parameters are invalidate
        videoFrameTypeIDR       #IDR frame in H.264
        videoFrameTypeI         #I frame type
        videoFrameTypeP         #P frame type
        videoFrameTypeSkip      #skip the frame based encoder kernel
        videoFrameTypeIPMixed   #a frame where I and P slices are mixing, not supported yet

    ctypedef enum EVideoFormatType:
        videoFormatRGB              #rgb color formats
        videoFormatRGBA
        videoFormatRGB555
        videoFormatRGB565
        videoFormatBGR
        videoFormatBGRA
        videoFormatABGR
        videoFormatARGB
        videoFormatYUY2
        videoFormatYVYU
        videoFormatUYVY
        videoFormatI420
        videoFormatYV12
        videoFormatInternal         #only used in SVC decoder testbed
        videoFormatNV12             #new format for output by DXVA decoding
        videoFormatVFlip

cdef extern from "wels/codec_api.h":
    ctypedef void *WelsTraceCallback(void* ctx, int level, const char* string)
    cdef cppclass ISVCEncoder:
        long Initialize(const SEncParamBase* pParam) nogil
        long Uninitialize() nogil
        int InitializeExt(const SEncParamExt* pParam) nogil
        int GetDefaultParams(SEncParamExt* pParam) nogil
        int SetOption(ENCODER_OPTION eOptionId, void* pOption)
        int EncodeFrame(const SSourcePicture* kpSrcPic, SFrameBSInfo* pBsInfo) nogil

    void WelsGetCodecVersionEx(OpenH264Version* pVersion)
    int WelsCreateSVCEncoder(ISVCEncoder** ppDecoder) nogil
    void WelsDestroySVCEncoder(ISVCEncoder* pDecoder) nogil


FRAME_TYPES: Dict[int, str] = {
    videoFrameTypeInvalid   : "invalid",
    videoFrameTypeIDR       : "IDR",
    videoFrameTypeI         : "I",
    videoFrameTypeP         : "P",
    videoFrameTypeSkip      : "skip",
    videoFrameTypeIPMixed   : "mixed",
}

COLORSPACES: Dict[str, str] = {
    "YUV420P"   : "YUV420P",
}


def get_version() -> Tuple[int, int, int]:
    cdef OpenH264Version version
    WelsGetCodecVersionEx(&version)
    return (version.uMajor, version.uMinor, version.uRevision)


def get_type() -> str:
    return "openh264"


def get_info() -> Dict[str, Any]:
    return {
        "version"   : get_version(),
    }


def get_encodings() -> Sequence[str]:
    return ("h264", )


# actual limits (which we cannot reach because we hit OOM):
# MAX_WIDTH, MAX_HEIGHT = (16384, 16384)
MAX_WIDTH, MAX_HEIGHT = (3840, 2160)

def get_specs() -> Sequence[VideoSpec]:
    specs: Sequence[VideoSpec] = []

    for encoding in get_encodings():
        for in_cs in tuple(COLORSPACES.keys()):
            out_cs = in_cs
            # we can handle high quality and any speed
            # setup cost is moderate (about 10ms)
            specs.append(VideoSpec(
                    encoding=encoding, input_colorspace=in_cs, output_colorspaces=(out_cs, ),
                    has_lossless_mode=False,
                    codec_class=Encoder, codec_type=get_type(),
                    quality=40, speed=20,
                    size_efficiency=40,
                    setup_cost=0, width_mask=0xFFFE, height_mask=0xFFFE,
                    max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
                )
            )
    return specs

generation = AtomicInteger()


#cdef void log_cb(void* context, int level, const char* message) nogil:
#    pass #nothing yet


cdef class Encoder:
    cdef unsigned long frames
    cdef ISVCEncoder *context
    cdef unsigned int width
    cdef unsigned int height
    cdef object src_format
    cdef uint8_t ready
    cdef object file

    cdef object __weakref__

    def init_context(self, encoding: str, unsigned int width, unsigned int height, src_format: str,
                     options: typedict) -> None:
        log("openh264.init_context%s", (encoding, width, height, src_format, options))
        assert src_format=="YUV420P", "invalid source format: %s, must be one of: %s" % (src_format, csv(COLORSPACES.keys()))
        assert encoding=="h264", "invalid encoding: %s" % encoding
        assert options.intget("scaled-width", width)==width, "openh264 encoder does not handle scaling"
        assert options.intget("scaled-height", height)==height, "openh264 encoder does not handle scaling"
        if width%2 != 0 or height% 2!= 0:
            raise ValueError(f"invalid odd width {width} or height {height} for {src_format}")
        self.width = width
        self.height = height
        self.src_format = src_format
        self.frames = 0
        self.init_encoder(options)
        gen = generation.increase()
        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+"openh264-"+str(gen)+f".{encoding}"
            self.file = open(filename, "wb")
            log.info(f"saving {encoding} stream to {filename!r}")
        self.ready = 1

    def is_ready(self) -> bool:
        return bool(self.ready)

    cdef void init_encoder(self, options:typedict):
        cdef int r = 0
        with nogil:
            r = WelsCreateSVCEncoder(&self.context)
        log("WelsCreateSVCEncoder context=%#x", <uintptr_t> self.context)
        if r or self.context==NULL:
            raise RuntimeError(f"failed to create openh264 svc encoder, error {r}")
        cdef int trace_level = WELS_LOG_ERROR
        self.context.SetOption(ENCODER_OPTION_TRACE_LEVEL, &trace_level)
        #self.context.SetOption(ENCODER_OPTION_TRACE_CALLBACK, <void*> &log_cb)
        #self.context.SetOption(ENCODER_OPTION_TRACE_CALLBACK_CONTEXT, NULL)
        cdef int videoFormat = videoFormatI420
        self.context.SetOption(ENCODER_OPTION_DATAFORMAT, &videoFormat)
        cdef int level = LEVEL_4_1
        self.context.SetOption(ENCODER_OPTION_LEVEL, &level)

        cdef SEncParamExt param
        memset(&param, 0, sizeof(SEncParamExt))
        with nogil:
            r = self.context.GetDefaultParams(&param)
        if r:
            raise RuntimeError("failed to get default openh264 encoder parameters")
        param.iUsageType    = SCREEN_CONTENT_REAL_TIME
        param.fMaxFrameRate = 30
        param.iPicWidth     = self.width
        param.iPicHeight    = self.height
        param.iRCMode       = RC_OFF_MODE
        # assume that the images we will be encoding are in YUV420P full-range:
        param.sSpatialLayers[0].bFullRange = True
        #param.iTargetBitrate = 5000000
        with nogil:
            r = self.context.InitializeExt(&param)
        if r:
            raise RuntimeError("failed to initialize openh264 encoder context")
        #cdef int profile = PRO_MAIN
        #self.context.SetOption(ENCODER_OPTION_PROFILE, &profile)
        #a void (*)(void* context, int level, const char* message) function which receives log messages
        trace_level = WELS_LOG_WARNING
        self.context.SetOption(ENCODER_OPTION_TRACE_LEVEL, &trace_level)
        for i in range(param.iSpatialLayerNum):
            log("spatial layer %i bFullRange=%s", i, param.sSpatialLayers[i].bFullRange)

    def clean(self) -> None:
        log("openh264 close context %#x", <uintptr_t> self.context)
        cdef ISVCEncoder *context = self.context
        if context!=NULL:
            self.context = NULL
            with nogil:
                context.Uninitialize()
                WelsDestroySVCEncoder(context)
        self.frames = 0
        self.width = 0
        self.height = 0
        f = self.file
        if f:
            self.file = None
            f.close()

    def get_info(self) -> Dict[str,Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
        }
        return info

    def __repr__(self):
        if not self.ready:
            return "openh264_encoder(uninitialized)"
        return f"openh264_encoder({self.width}x{self.height})"

    def is_closed(self) -> bool:
        return not bool(self.ready)

    def get_encoding(self) -> str:
        return "h264"

    def __dealloc__(self):
        self.clean()

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "openh264"

    def get_src_format(self) -> str:
        return self.src_format

    def compress_image(self, image: ImageWrapper, options: typedict) -> Tuple[bytes, Dict]:
        cdef int i
        cdef unsigned int width = image.get_width()
        cdef unsigned int height = image.get_height()
        assert width>=self.width
        assert height>=self.height
        if image.get_pixel_format()!="YUV420P":
            raise ValueError("expected YUV420P but got %s" % image.get_pixel_format())
        pixels = image.get_pixels()
        strides = image.get_rowstride()

        #encoder.SetOption(ENCODER_OPTION_SVC_ENCODE_PARAM_BASE, &param)

        cdef SFrameBSInfo frame_info
        memset(&frame_info, 0, sizeof(SFrameBSInfo))
        cdef SSourcePicture pic
        memset(&pic, 0, sizeof(SSourcePicture))
        pic.iPicWidth = width
        pic.iPicHeight = height
        pic.iColorFormat = videoFormatI420
        pic.iStride[0] = strides[0]
        pic.iStride[1] = strides[1]
        pic.iStride[2] = strides[2]

        cdef Py_buffer py_buf[3]
        for i in range(3):
            memset(&py_buf[i], 0, sizeof(Py_buffer))
        cdef int r
        try:
            assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
            assert len(strides)==3, "image strides does not have 3 values! (found %s)" % len(strides)
            for i in range(3):
                if PyObject_GetBuffer(pixels[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                    raise ValueError("failed to read pixel data from %s" % type(pixels[i]))
                pic.pData[i] = <uint8_t*> py_buf[i].buf
            with nogil:
                r = self.context.EncodeFrame(&pic, &frame_info)
        finally:
            for i in range(3):
                if py_buf[i].buf:
                    PyBuffer_Release(&py_buf[i])
        if r:
            raise RuntimeError(f"openh264 failed to encode frame, error {r}")
        client_options = {
            "frame": self.frames,
            "full-range": image.get_full_range(),
        }
        if frame_info.eFrameType == videoFrameTypeInvalid:
            raise ValueError("invalid frame type")
        elif frame_info.eFrameType == videoFrameTypeIDR:
            client_options["type"] = "IDR"
        # elif frame_info.eFrameType == videoFrameTypeI:
        #    client_options["type"] = "I"
        # elif frame_info.eFrameType == videoFrameTypeP:
        #    client_options["type"] = "P"
        self.frames += 1
        if frame_info.eFrameType==videoFrameTypeSkip:
            client_options["skip"] = True
            return b"", client_options
        data = []
        cdef SLayerBSInfo* layer_info
        for layer in range(frame_info.iLayerNum):
            layer_info = &frame_info.sLayerInfo[layer]
            if layer_info==NULL:
                log.warn(f"Warning: openh264 layer {layer} is NULL")
                continue
            log(f"layer {layer}: {layer_info.iNalCount} nals")
            layer_size = 0
            for nal in range(layer_info.iNalCount-1, -1, -1):
                size = layer_info.pNalLengthInByte[nal]
                log(f" nal {nal}: {size:6} bytes")
                layer_size += size
            if layer_size:
                data.append(layer_info.pBsBuf[:layer_size])
        if len(data)==1:
            bdata = data[0]
        else:
            bdata = b"".join(data)
        log(f"openh264 compress_image: {len(bdata)} bytes for frame {self.frames}")
        return bdata, client_options


def selftest(full=False) -> None:
    log("openh264 selftest: %s", get_info())
    global SAVE_TO_FILE
    from xpra.codecs.checks import testencoder, get_encoder_max_sizes
    from xpra.codecs.openh264 import encoder
    temp = SAVE_TO_FILE
    try:
        SAVE_TO_FILE = None
        assert testencoder(encoder, full, typedict())
    finally:
        SAVE_TO_FILE = temp
