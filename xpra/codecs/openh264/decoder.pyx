# This file is part of Xpra.
# Copyright (C) 2022-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from time import monotonic
from typing import Dict, Any

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger
log = Logger("encoder", "openh264")

from libc.string cimport memset
from libc.stdint cimport uint8_t, uintptr_t
from xpra.buffers.membuf cimport buffer_context #pylint: disable=syntax-error

cdef extern from "wels/codec_app_def.h":
    int VIDEO_BITSTREAM_AVC
    int VIDEO_BITSTREAM_SVC
    int VIDEO_BITSTREAM_DEFAULT
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

    ctypedef struct SDecodingParam:
        pass
    cdef cppclass ISVCDecoder:
        long Initialize(const SDecodingParam* pParam)
        long Uninitialize()
        long DecodeFrameNoDelay(const unsigned char* pSrc, const int iSrcLen,
                                unsigned char** ppDst, SBufferInfo* pDstInfo) nogil


COLORSPACES = {
    "YUV420P"   : "YUV420P",
    }

def init_module():
    log("openh264.init_module()")

def cleanup_module():
    log("openh264.cleanup_module()")

def get_version():
    cdef OpenH264Version version
    WelsGetCodecVersionEx(&version)
    return (version.uMajor, version.uMinor, version.uRevision)

def get_type():
    return "openh264"

def get_info():
    return {
        "version"   : get_version(),
        "formats"   : tuple(COLORSPACES.keys()),
        }

def get_encodings():
    return ("h264", )

def get_min_size(encoding):
    return 32, 32

def get_input_colorspaces(encoding):
    assert encoding in get_encodings()
    return tuple(COLORSPACES.keys())

def get_output_colorspace(encoding, input_colorspace):
    assert encoding in get_encodings()
    assert input_colorspace in COLORSPACES
    return input_colorspace


cdef class Decoder:
    cdef ISVCDecoder *context;
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object colorspace

    cdef object __weakref__

    def init_context(self, encoding, int width, int height, colorspace):
        log("openh264.init_context%s", (encoding, width, height, colorspace))
        assert encoding=="h264", f"invalid encoding: {encoding}"
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


    def get_encoding(self):
        return "h264"

    def get_colorspace(self):
        return self.colorspace

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def is_closed(self):
        return self.context!=NULL

    def get_type(self):
        return "openh264"

    def __dealloc__(self):
        self.clean()

    def clean(self):
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

    def get_info(self) -> Dict[str,Any]:
        info = get_info()
        info.update({
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "colorspace"    : self.colorspace,
            })
        return info


    def decompress_image(self, data, options=None):
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
                r = self.context.DecodeFrameNoDelay(<const unsigned char*> src, <const int> src_len,
                                                    yuv, &buf_info)
        if r:
            raise RuntimeError(f"openh264 frame decoding error {r}")
        end = monotonic()
        cdef int ystride = buf_info.UsrData.sSystemBuffer.iStride[0]
        cdef int uvstride = buf_info.UsrData.sSystemBuffer.iStride[1]
        strides = [ystride, uvstride, uvstride]
        cdef int width = buf_info.UsrData.sSystemBuffer.iWidth
        cdef int height = buf_info.UsrData.sSystemBuffer.iHeight
        if width>self.width or height>self.height:
            log.warn("Warning: image bigger than expected")
            log.warn(f" {width}x{height} instead of {self.width}x{self.height}")
        pixels = [
            yuv[0][:ystride*height],
            yuv[1][:uvstride*(height//2)],
            yuv[2][:uvstride*(height//2)],
            ]
        log(f"openh264 decoded {src_len:8} bytes into {width}x{height} YUV420P in {int((end-start)*1000):3}ms")
        return ImageWrapper(0, 0, width, height, pixels, self.colorspace, 24, strides, 1, ImageWrapper.PLANAR_3)


def selftest(full=False):
    log("openh264 selftest: %s", get_info())
    from xpra.codecs.codec_checks import testdecoder
    from xpra.codecs.openh264 import decoder
    testdecoder(decoder, full)
