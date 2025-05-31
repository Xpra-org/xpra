# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec
from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger
log = Logger("encoder", "openh264")

from libcpp cimport bool as bool_t
from libc.string cimport memset
from libc.stdint cimport uint8_t, uintptr_t
from xpra.buffers.membuf cimport buffer_context  # pylint: disable=syntax-error

cdef extern from "wels/codec_app_def.h":
    ctypedef enum DECODING_STATE:
        dsErrorFree             # bit stream error-free
        dsFramePending          # need more throughput to generate a frame output,
        dsRefLost               # layer lost at reference frame with temporal id 0
        dsBitstreamError        # error bitstreams(maybe broken internal frame) the decoder cared
        dsDepLayerLost          # dependented layer is ever lost
        dsNoParamSets           # no parameter set NALs involved
        dsDataErrorConcealed    # current data error concealed specified
        dsRefListNullPtrs       # ref picure list contains null ptrs within uiRefCount range

        # Errors derived from logic level
        dsInvalidArgument       # invalid argument specified
        dsInitialOptExpected    # initializing operation is expected
        dsOutOfMemory           # out of memory due to new request
        dsDstBufNeedExpan       # actual picture size exceeds size of dst pBuffer feed in decoder, so need expand its size

    ctypedef struct OpenH264Version:
        unsigned int uMajor
        unsigned int uMinor
        unsigned int uRevision
        unsigned int uReserved

cdef extern from "wels/codec_def.h":
    ctypedef struct SSysMEMBuffer:
        int iWidth                          #width of decoded pic for display
        int iHeight                         #height of decoded pic for display
        int iFormat                         #type is "EVideoFormatType"
        int iStride[2]                      #stride of 2 component

    cdef union UsrData:
        SSysMEMBuffer sSystemBuffer         #memory info for one picture

    ctypedef struct SBufferInfo:
        int iBufferStatus                   #0: one frame data is not ready; 1: one frame data is ready
        unsigned long long uiInBsTimeStamp  #input BS timestamp
        unsigned long long uiOutYuvTimeStamp#output YUV timestamp, when bufferstatus is 1
        UsrData UsrData #output buffer info
        unsigned char* pDst[3]              #point to picture YUV data

cdef extern from "wels/codec_api.h":
    void WelsGetCodecVersionEx(OpenH264Version* pVersion)
    long WelsCreateDecoder(ISVCDecoder** ppDecoder)
    void WelsDestroyDecoder(ISVCDecoder* pDecoder)

    ctypedef enum ERROR_CON_IDC:
        ERROR_CON_DISABLE
        ERROR_CON_FRAME_COPY
        ERROR_CON_SLICE_COPY
        ERROR_CON_FRAME_COPY_CROSS_IDR
        ERROR_CON_SLICE_COPY_CROSS_IDR
        ERROR_CON_SLICE_COPY_CROSS_IDR_FREEZE_RES_CHANGE
        ERROR_CON_SLICE_MV_COPY_CROSS_IDR
        ERROR_CON_SLICE_MV_COPY_CROSS_IDR_FREEZE_RES_CHANGE

    ctypedef enum VIDEO_BITSTREAM_TYPE:
        VIDEO_BITSTREAM_AVC
        VIDEO_BITSTREAM_SVC
        VIDEO_BITSTREAM_DEFAULT

    ctypedef struct SVideoProperty:
        unsigned int          size          # size of the struct
        VIDEO_BITSTREAM_TYPE  eVideoBsType

    ctypedef struct SDecodingParam:
        char*     pFileNameRestructed       # file name of reconstructed frame used for PSNR calculation based debug
        unsigned int  uiCpuLoad             # CPU load
        unsigned char uiTargetDqLayer       # setting target dq layer id
        ERROR_CON_IDC eEcActiveIdc          # whether active error concealment feature in decoder
        bool_t bParseOnly                     # decoder for parse only, no reconstruction. When it is true, SPS/PPS size should not exceed SPS_PPS_BS_SIZE (128). Otherwise, it will return error info
        SVideoProperty   sVideoProperty

    cdef cppclass ISVCDecoder:
        long Initialize(const SDecodingParam* pParam)
        long Uninitialize()
        long DecodeFrameNoDelay(const unsigned char* pSrc, const int iSrcLen,
                                unsigned char** ppDst, SBufferInfo* pDstInfo) nogil

ERROR_STR: Dict[int, str] = {
    dsErrorFree: "no error",
    dsFramePending: "need more throughput to generate a frame output",
    dsRefLost: "layer lost at reference frame with temporal id 0",
    dsBitstreamError: "error bitstreams(maybe broken internal frame) the decoder cared",
    dsDepLayerLost: "dependented layer is ever lost",
    dsNoParamSets: "no parameter set NALs involved",
    dsDataErrorConcealed: "current data error concealed specified",
    dsRefListNullPtrs: "ref picure list contains null ptrs within uiRefCount range",

    # Errors derived from logic level
    dsInvalidArgument: "invalid argument specified",
    dsInitialOptExpected: "initializing operation is expected",
    dsOutOfMemory: "out of memory due to new request",
    dsDstBufNeedExpan: "actual picture size exceeds size of dst pBuffer feed in decoder, so need expand its size",
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


def get_min_size(encoding) -> Tuple[int, int]:
    return 32, 32


MAX_WIDTH, MAX_HEIGHT = (8192, 4096)


def get_specs() -> Sequence[VideoSpec]:
    return (
        VideoSpec(
            encoding="h264", input_colorspace="YUV420P", output_colorspaces=("YUV420P", ),
            has_lossless_mode=False,
            codec_class=Decoder, codec_type=get_type(),
            quality=40, speed=20,
            size_efficiency=40,
            setup_cost=0, width_mask=0xFFFE, height_mask=0xFFFE,
            max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
        ),
    )


cdef class Decoder:
    cdef ISVCDecoder *context;
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object colorspace

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("openh264.init_context%s", (encoding, width, height, colorspace))
        assert encoding == "h264", f"invalid encoding: {encoding}"
        assert colorspace == "YUV420P", f"invalid colorspace: {colorspace}"
        self.width = width
        self.height = height
        self.colorspace = colorspace
        self.frames = 0
        cdef long r = WelsCreateDecoder(&self.context)
        if r:
            raise RuntimeError(f"error {r} creating openh264 decoder")
        cdef SDecodingParam dec_param
        memset(&dec_param, 0, sizeof(SDecodingParam))
        #dec_param.sVideoProperty.eVideoBsType = VIDEO_BITSTREAM_AVC;
        #for Parsing only, the assignment is mandatory
        #dec_param.bParseOnly = 0
        self.context.Initialize(&dec_param)

    def get_encoding(self) -> str:
        return "h264"

    def get_colorspace(self) -> str:
        return self.colorspace

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return self.context!=NULL

    def get_type(self) -> str:
        return "openh264"

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        log("openh264 close context %#x", <uintptr_t> self.context)
        cdef ISVCDecoder *context = self.context
        if context:
            context.Uninitialize()
            self.context = NULL
            WelsDestroyDecoder(context)
        self.frames = 0
        self.width = 0
        self.height = 0
        self.colorspace = ""

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "colorspace"    : self.colorspace,
        }
        return info

    def decompress_image(self, data: bytes, options: typedict) -> ImageWrapper:
        cdef SBufferInfo buf_info
        cdef long r = 0
        cdef unsigned char* src
        cdef int src_len = 0
        cdef uint8_t *yuv[3]
        start = monotonic()
        with buffer_context(data) as bc:
            src = <unsigned char*> (<uintptr_t> int(bc))
            src_len = len(bc)
            with nogil:
                r = self.context.DecodeFrameNoDelay(<const unsigned char*> src, <const int> src_len, yuv, &buf_info)
        if r:
            msg = ERROR_STR.get(r, "unknown")
            raise RuntimeError(f"openh264 frame decoding error {msg!r}")
        end = monotonic()
        cdef int ystride = buf_info.UsrData.sSystemBuffer.iStride[0]
        cdef int uvstride = buf_info.UsrData.sSystemBuffer.iStride[1]
        strides = (ystride, uvstride, uvstride)
        cdef int width = buf_info.UsrData.sSystemBuffer.iWidth
        cdef int height = buf_info.UsrData.sSystemBuffer.iHeight
        log(f"openh264 strides=%s, size=%s", strides, (width, height))
        if width < self.width:
            raise ValueError(f"stream width {width} is smaller than decoder width {self.width}")
        if height < self.height:
            raise ValueError(f"stream width {height} is smaller than decoder width {self.height}")
        cdef int wdelta = width - self.width
        cdef int hdelta = height - self.height
        if abs(wdelta) > 1 or abs(hdelta) > 1:
            if (wdelta & 0xffe0) > 0 or (hdelta & 0xfffe0) > 0:
                log.warn("Warning: image bigger than expected")
                log.warn(f" {width}x{height} instead of {self.width}x{self.height}")
        pixels = (
            yuv[0][:ystride*height],
            yuv[1][:uvstride*(height//2)],
            yuv[2][:uvstride*(height//2)],
        )
        log(f"openh264 decoded {src_len:8} bytes into {width}x{height} YUV420P in {int((end-start)*1000):3}ms")
        full_range = options.boolget("full-range")
        return ImageWrapper(0, 0, self.width, self.height, pixels, self.colorspace, 24, strides, 1, ImageWrapper.PLANAR_3, full_range=full_range)


def selftest(full=False) -> None:
    log("openh264 selftest: %s", get_info())
    from xpra.codecs.checks import testdecoder
    from xpra.codecs.openh264 import decoder
    testdecoder(decoder, full)
