# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import math
import time

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.log import Logger
log = Logger("encoder", "amf")

from xpra.codecs.constants import VideoSpec, get_subsampling_divs
from xpra.codecs.image import ImageWrapper
from xpra.os_util import WIN32
from xpra.util.env import envbool
from xpra.util.objects import typedict

from libc.stddef cimport wchar_t
from libc.stdint cimport uint8_t, uint64_t, uintptr_t
from libc.string cimport memset

from xpra.codecs.amf.amf cimport (
    set_guid,
    AMF_RESULT, AMF_EOF, AMF_REPEAT,
    AMF_DX11_0,
    AMF_MEMORY_TYPE,
    AMF_MEMORY_DX11,
    AMF_INPUT_FULL,
    AMF_SURFACE_FORMAT, AMF_SURFACE_YUV420P, AMF_SURFACE_NV12, AMF_SURFACE_BGRA,
    AMF_VARIANT_TYPE, AMF_VARIANT_INT64, AMF_VARIANT_RECT,
    AMF_VIDEO_ENCODER_USAGE_ULTRA_LOW_LATENCY,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_QUALITY,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_SPEED,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_BALANCED,
    AMF_VIDEO_ENCODER_AV1_LEVEL_5_1,
    AMF_VIDEO_ENCODER_AV1_PROFILE_MAIN,
    AMF_VIDEO_ENCODER_AV1_USAGE_ULTRA_LOW_LATENCY,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_HIGH_QUALITY,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_QUALITY,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_SPEED,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_BALANCED,
    AMF_VIDEO_ENCODER_HEVC_USAGE_ULTRA_LOW_LATENCY,
    AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED,
    amf_handle, amf_long, amf_int32,
    AMFDataAllocatorCB,
    AMFGuid,
    AMFBuffer,
    AMFComponentOptimizationCallback,
    AMFPlane,
    AMFData,
    AMFTrace,
    AMFVariantStruct,
    AMFVariantAssignInt64,
    AMFSurface,
    AMFContext,
    AMFComponent,
    AMFFactory,
)

from ctypes import c_uint64, c_int, c_void_p, byref, POINTER
from ctypes import CDLL

amf = CDLL("amfrt64")
AMFQueryVersion = amf.AMFQueryVersion
AMFQueryVersion.argtypes = [POINTER(c_uint64)]
AMFQueryVersion.restype = c_int
AMFInit = amf.AMFInit
AMFInit.argtypes = [c_uint64, c_void_p]
AMFQueryVersion.restype = c_int

DX11 = envbool("XPRA_AMF_DX11", WIN32)
SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")

AMF_DLL_NAME = "amfrt64.dll" if WIN32 else "libamf.so"


AMF_ENCODINGS : Dict[str, str] = {
    # AMFVideoEncoderVCE_SVC?
    "h264": "AMFVideoEncoderVCE_AVC",
    "hevc": "AMFVideoEncoder_HEVC",
    "av1": "AMFVideoEncoder_AV1",
}
START_TIME_PROPERTY = "StartTimeProperty"


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS
    # cdef extern from "unicodeobject.h":
    wchar_t* PyUnicode_AsWideCharString(object unicode, Py_ssize_t *size)
    object PyUnicode_FromWideChar(wchar_t *w, Py_ssize_t size)
    # cdef extern from "pymem.h":
    void PyMem_Free(void *ptr)


cdef extern from "string.h":
    size_t wcslen(const wchar_t *str)


cdef AMFFactory *factory = NULL


def init_module() -> None:
    log("amf.encoder.init_module() info=%s", get_info())
    version = get_c_version()
    cdef AMF_RESULT res = AMFInit(version, <uintptr_t> &factory)
    log(f"AMFInit: {res=}, factory=%s", <uintptr_t> factory)
    check(res, "AMF initialization")
    cdef AMFTrace *trace = NULL
    res = factory.pVtbl.GetTrace(factory, &trace)
    log(f"amf_encoder_init() GetTrace()={res}")
    if res == 0:
        log(f"Trace.GetGlobalLevel=%i", trace.pVtbl.GetGlobalLevel(trace))
        trace.pVtbl.SetGlobalLevel(trace, 0)

def cleanup_module() -> None:
    log("amf.encoder.cleanup_module()")
    factory = NULL


cdef uint64_t get_c_version():
    from ctypes import c_uint64, c_int, byref, POINTER
    from ctypes import CDLL
    amf = CDLL("amfrt64")
    version = c_uint64()
    AMFQueryVersion = amf.AMFQueryVersion
    AMFQueryVersion.argtypes = [POINTER(c_uint64)]
    AMFQueryVersion.restype = c_int
    res = AMFQueryVersion(byref(version))
    if res:
        return 0
    return int(version.value)


def check(res: AMF_RESULT, message: str):
    if res == 0:
        return
    error = error_str(res) or f"error {res}"
    raise RuntimeError(f"{message}: {error}")


def error_str(AMF_RESULT result) -> str:
    if result == 0:
        return ""
    cdef AMFTrace *trace = NULL
    cdef AMF_RESULT res = factory.pVtbl.GetTrace(factory, &trace)
    if res != 0:
        return ""
    cdef const wchar_t *text = trace.pVtbl.GetResultText(trace, result)
    cdef size_t size = wcslen(text)
    return PyUnicode_FromWideChar(text, size)


def get_version() -> Sequence[int]:
    version = get_c_version()
    return version >> 48, (version >> 32) & 0xffff, (version >> 16) & 0xffff, version & 0xffff


def get_type() -> str:
    return "amf"


CODECS = tuple(AMF_ENCODINGS.keys())

def get_encodings() -> Sequence[str]:
    return CODECS


def get_input_colorspaces(encoding: str) -> Sequence[str]:
    assert encoding in get_encodings(), "invalid encoding: %s" % encoding
    # return ("YUV420P", "NV12", "BGRA")
    return ("NV12", )


def get_output_colorspaces(encoding: str, input_colorspace: str) -> Sequence[str]:
    assert encoding in get_encodings(), "invalid encoding: %s" % encoding
    assert input_colorspace in get_input_colorspaces(encoding)
    return ("YUV420P", )


def get_info() -> Dict[str, Any]:
    info = {
        "version"       : get_version(),
        "encodings"     : get_encodings(),
    }
    return info


def get_specs(encoding: str, colorspace: str) -> Sequence[VideoSpec]:
    assert encoding in get_encodings(), "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in get_input_colorspaces(encoding), "invalid colorspace: %s (must be one of %s)" % (colorspace, get_input_colorspaces(encoding))
    # setup cost is reasonable (usually about 5ms)
    max_w, max_h = 3840, 2160
    has_lossless_mode = False
    speed = 50
    quality = 50
    return (
        VideoSpec(
            encoding=encoding, input_colorspace=colorspace, output_colorspaces=[colorspace],
            has_lossless_mode=False,
            codec_class=Encoder, codec_type=get_type(),
            quality=quality, speed=speed,
            size_efficiency=60,
            setup_cost=20, max_w=max_w, max_h=max_h),
        )


cdef class Encoder:
    cdef AMFContext *context
    cdef AMFComponent* encoder
    cdef AMF_SURFACE_FORMAT surface_format
    cdef AMFSurface* surface
    cdef void *device
    cdef unsigned long frames
    cdef unsigned int width
    cdef unsigned int height
    cdef object encoding
    cdef object src_format
    cdef int speed
    cdef int quality
    cdef object file

    cdef object __weakref__

    def init_context(self, encoding: str,
                     unsigned int width, unsigned int height,
                     src_format: str,
                     options: typedict) -> None:
        log("amf init_context%s", (encoding, width, height, src_format, options))
        assert encoding in get_encodings(), "invalid encoding: %s" % encoding
        assert options.get("scaled-width", width)==width, "amf encoder does not handle scaling"
        assert options.get("scaled-height", height)==height, "amf encoder does not handle scaling"
        assert encoding in get_encodings()
        assert src_format in get_input_colorspaces(encoding), f"invalid source format {src_format!r} for {encoding}"
        self.src_format = src_format
        if src_format == "YUV420P":
            self.surface_format = AMF_SURFACE_YUV420P
        elif src_format == "NV12":
            self.surface_format = AMF_SURFACE_NV12
        elif src_format == "BGRA":
            self.surface_format = AMF_SURFACE_BGRA
        else:
            raise ValueError("invalid pixel format {src_format!r}")

        self.encoding = encoding
        self.width = width
        self.height = height
        self.quality = options.intget("quality", 50)
        self.speed = options.intget("speed", 50)
        self.frames = 0

        self.context = NULL
        self.encoder = NULL
        self.surface = NULL
        self.device = NULL

        self.amf_context_init()
        self.amf_surface_init()
        self.amf_encoder_init(options)

        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+f"amf-{self.generation}.{encoding}"
            self.file = open(filename, "wb")
            log.info(f"saving {encoding} stream to {filename!r}")

    def check(self, res: AMF_RESULT, message: str):
        if res:
            check(res, message)
            self.clean()

    def amf_context_init(self) -> None:
        assert factory
        cdef AMF_RESULT res = factory.pVtbl.CreateContext(factory, &self.context)
        log(f"amf_context_init() CreateContext()={res}")
        self.check(res, "AMF context initialization")
        if DX11:
            res = self.context.pVtbl.InitDX11(self.context, NULL, AMF_DX11_0)
            log(f"amf_context_init() InitDX11()={res}")
            self.check(res, "AMF DX11 device initialization")
            self.device = self.context.pVtbl.GetDX11Device(self.context, AMF_DX11_0)
        else:
            res = self.context.pVtbl.InitOpenGL(self.context, NULL, NULL, NULL)
            log(f"amf_context_init() InitOpenGL()={res}")
            self.check(res, "AMF OpenGL device initialization")
            self.device = <void *> self.context.pVtbl.GetOpenGLContext(self.context)
        log(f"amf_context_init() device=%#x", <uintptr_t> self.device)

    def amf_surface_init(self) -> None:
        assert DX11
        cdef AMF_MEMORY_TYPE memory = AMF_MEMORY_DX11
        cdef AMF_RESULT res = self.context.pVtbl.AllocSurface(self.context, memory, self.surface_format, self.width, self.height, &self.surface)
        self.check(res, "AMF surface initialization for {self.width}x{self.height} {self.src_format}")
        log(f"amf_surface_init() surface=%#x", <uintptr_t> self.surface)

    cdef void set_encoder_property(self, name: str, variant: AMF_VARIANT_TYPE, value):
        cdef AMFVariantStruct var
        AMFVariantAssignInt64(&var, value)
        cdef wchar_t *prop = PyUnicode_AsWideCharString(name, NULL)
        ret = self.encoder.pVtbl.SetProperty(self.encoder, prop, var)
        self.check(ret, f"AMF encoder setting property {name} to {value}")
        PyMem_Free(prop)

    def amf_encoder_init(self, options: typedict) -> None:
        assert factory and self.context
        log(f"amf_encoder_init() for encoding {self.encoding!r}")

        amf_codec_name = str(AMF_ENCODINGS[self.encoding])
        cdef wchar_t *amf_codec = PyUnicode_AsWideCharString(amf_codec_name, NULL)
        cdef AMF_RESULT res = factory.pVtbl.CreateComponent(factory, self.context, amf_codec, &self.encoder)
        PyMem_Free(amf_codec)
        log(f"amf_encoder_init() CreateComponent()={res}")
        self.check(res, f"AMF {self.encoding!r} encoder creation")

        speed = options.intget("speed", 50)
        quality = options.intget("quality", 50)
        bwlimit = options.intget("bandwidth-limit", 0)

        def setint64(prop: str, value: int) -> None:
            self.set_encoder_property(prop, AMF_VARIANT_INT64, value)

        # tune encoder:
        if self.encoding == "h264":
            setint64("Usage", value=AMF_VIDEO_ENCODER_USAGE_ULTRA_LOW_LATENCY)
            if quality >= 80:
                setint64("QualityPreset", value=AMF_VIDEO_ENCODER_QUALITY_PRESET_QUALITY)
            elif speed >= 80:
                setint64("QualityPreset", value=AMF_VIDEO_ENCODER_QUALITY_PRESET_SPEED)
            else:
                setint64("QualityPreset", value=AMF_VIDEO_ENCODER_QUALITY_PRESET_BALANCED)

            if bwlimit:
                setint64("TargetBitrate", value=bwlimit)

            if False:
                #AMFRect(w, h)
                #self.set_encoder_property("FrameSize", AMF_VARIANT_RECT, rect)
                #AMFRate(1, rate)
                #self.set_encoder_property("FrameRate", AMF_VARIANT_RATE, rate)
                #4K:
                setint64("Profile", value=AMF_VIDEO_ENCODER_PROFILE_HIGH)
                setint64("ProfileLevel", value=AMF_H264_LEVEL__5_1)

            if not options.boolget("b-frames", False):
                setint64("BPicturesPattern", value=0)
                # can be not supported - check Capability Manager sample
        elif self.encoding == "av1":
            setint64("Av1Usage", value=AMF_VIDEO_ENCODER_AV1_USAGE_ULTRA_LOW_LATENCY)
            setint64("Av1Profile", AMF_VIDEO_ENCODER_AV1_PROFILE_MAIN)
            setint64("Av1Level", AMF_VIDEO_ENCODER_AV1_LEVEL_5_1)

            if bwlimit:
                setint64("Av1TargetBitrate", bwlimit)

            if quality >= 90:
                setint64("Av1QualityPreset", value=AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_HIGH_QUALITY)
            elif quality >= 90:
                setint64("Av1QualityPreset", value=AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_QUALITY)
            elif speed >= 80:
                setint64("Av1QualityPreset", value=AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_SPEED)
            else:
                setint64("Av1QualityPreset", value=AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_BALANCED)

            #"Av1FrameSize", size)
            #"Av1FrameRate, rate)
            if False:
                setint64("Av1AlignmentMode", AMF_VIDEO_ENCODER_AV1_ALIGNMENT_MODE_NO_RESTRICTIONS)
        elif self.encoding == "hevc":
            setint64("HevcUsage", AMF_VIDEO_ENCODER_HEVC_USAGE_ULTRA_LOW_LATENCY)
            setint64("HevcQualityPreset", AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED)
            #"HevcFrameRate", framerate)
            #"HevcFrameSize", size)
            if bwlimit:
                setint64("HevcTargetBitrate", bwlimit)

            #AMF_ASSIGN_PROPERTY_INT64(res, encoder, AMF_VIDEO_ENCODER_HEVC_TIER, AMF_VIDEO_ENCODER_HEVC_TIER_HIGH)
            #AMF_ASSIGN_PROPERTY_INT64(res, encoder, AMF_VIDEO_ENCODER_HEVC_PROFILE_LEVEL, AMF_LEVEL_5_1)
        else:
            raise RuntimeError(f"unexpected encoding {self.encoding!r}")

        # init:
        res = self.encoder.pVtbl.Init(self.encoder, self.surface_format, self.width, self.height)
        self.check(res, "AMF {self.encoding!r} encoder initialization for {self.width}x{self.height} {self.src_format}")
        log(f"amf_encoder_init() {self.encoding} encoder initialized at %#x", <uintptr_t> self.encoder)

    def is_ready(self) -> bool:
        return self.encoder != NULL

    def __repr__(self):
        return "amf.Encoder(%s)" % self.encoding

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"    : int(self.frames),
            "width"     : self.width,
            "height"    : self.height,
            "speed"     : self.speed,
            "quality"   : self.quality,
            "encoding"  : self.encoding,
            "src_format": self.src_format,
        }

    def get_encoding(self) -> str:
        return self.encoding

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return self.context==NULL

    def get_type(self) -> str:
        return "amf"

    def get_src_format(self) -> str:
        return self.src_format

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        log("clean() surface=%s", <uintptr_t> self.surface)
        cdef AMFSurface* surface = self.surface
        if surface:
            self.surface = NULL
            surface.pVtbl.Release(surface)
        log("clean() encoder=%s", <uintptr_t> self.encoder)
        cdef AMFComponent* encoder = self.encoder
        if encoder:
            self.encoder = NULL
            encoder.pVtbl.Terminate(encoder)
            encoder.pVtbl.Release(encoder)
        log("clean() context=%s", <uintptr_t> self.context)
        cdef AMFContext *context = self.context
        if context:
            self.context = NULL
            context.pVtbl.Terminate(context)
            context.pVtbl.Release(context)
        self.frames = 0
        self.width = 0
        self.height = 0
        self.encoding = ""
        self.src_format = ""
        f = self.file
        if f:
            self.file = None
            f.close()

    def compress_image(self, image: ImageWrapper, options: typedict) -> Tuple[bytes, Dict]:
        cdef uint8_t *pic_in[2]
        cdef int strides[2]
        cdef int sizes[2]
        assert self.context!=NULL
        pixels = image.get_pixels()
        istrides = image.get_rowstride()
        cdef int full_range = int(image.get_full_range())
        pf = image.get_pixel_format().replace("A", "X")
        if pf != self.src_format:
            raise ValueError(f"expected {self.src_format} but got {image.get_pixel_format()}")
        assert image.get_width()==self.width, "invalid image width %s, expected %s" % (image.get_width(), self.width)
        assert image.get_height()==self.height, "invalid image height %s, expected %s" % (image.get_height(), self.height)
        assert pixels, "failed to get pixels from %s" % image
        assert len(pixels)==2, "image pixels does not have 2 planes! (found %s)" % len(pixels)
        assert len(istrides)==2, "image strides does not have 2 values! (found %s)" % len(istrides)
        divs = get_subsampling_divs(self.src_format)

        cdef int speed = options.intget("speed", 50)
        if speed>=0:
            self.set_encoding_speed(speed)
        cdef int quality = options.intget("quality", 50)
        if quality>=0:
            self.set_encoding_quality(quality)

        cdef Py_buffer py_buf[2]
        for i in range(2):
            memset(&py_buf[i], 0, sizeof(Py_buffer))
        try:
            for i in range(2):
                xdiv, ydiv = divs[i]
                if PyObject_GetBuffer(pixels[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                    raise ValueError(f"failed to read pixel data from {type(pixels[i])}")
                assert istrides[i]>=self.width//xdiv, "invalid stride %i for width %i" % (istrides[i], self.width)
                assert py_buf[i].len>=istrides[i]*(self.height//ydiv), "invalid buffer length %i for plane %s, at least %i needed" % (
                    py_buf[i].len, "YUV"[i], istrides[i]*(self.height//ydiv))
                pic_in[i] = <uint8_t *> py_buf[i].buf
                strides[i] = istrides[i]
                sizes[i] = istrides[i] * (self.height // ydiv)
            return self.do_compress_image(pic_in, strides, sizes), {
                "csc"       : self.src_format,
                "frame"     : int(self.frames),
                "full-range" : bool(full_range),
                #"quality"  : min(99+self.lossless, self.quality),
                #"speed"    : self.speed,
            }
        finally:
            for i in range(2):
                if py_buf[i].buf:
                    PyBuffer_Release(&py_buf[i])

    cdef void set_surface_property(self, name: str, variant: AMF_VARIANT_TYPE, value: int64_t):
        cdef AMFVariantStruct var
        AMFVariantAssignInt64(&var, value)
        cdef wchar_t *prop = PyUnicode_AsWideCharString(name, NULL)
        self.surface.pVtbl.SetProperty(self.surface, prop, var)
        PyMem_Free(prop)

    cdef bytes do_compress_image(self, uint8_t *pic_in[2], int strides[2], int sizes[2]):
        cdef unsigned long start_time = 0    # nanoseconds!
        cdef AMFPlane *plane
        cdef uintptr_t dst_texture

        if not WIN32:
            raise ImportError("amf encoder needs porting to this platform")

        from xpra.platform.win32.d3d11.device import D3D11Device
        log("D3D11Device(%#x)", <uintptr_t> self.device)
        device = D3D11Device(<uintptr_t> self.device)
        with device.get_device_context() as dc:
            log("device: %s", device.get_info())
            log("device context: %s", dc.get_info())
            for plane_index in range(2):
                # get the D3D11 destination surface pointer for this plane:
                plane = self.surface.pVtbl.GetPlaneAt(self.surface, plane_index)
                assert plane
                log("plane %s=%s", ["Y", "UV"][plane_index], self.get_plane_info(plane))
                # texture is a `ID3D11Texture2D`:
                dst_texture = <uintptr_t> plane.pVtbl.GetNative(plane)
                log("texture=%#x, source=%#x", dst_texture, <uintptr_t> pic_in[plane_index])
                assert dst_texture
                box = ()
                #dc.update_subresource(dst_texture, 0, box,
                #                      <uintptr_t> pic_in[plane_index], strides[plane_index], sizes[plane_index])
            dc.flush()

        ns = round(1000 * 1000 * monotonic())
        self.set_surface_property(START_TIME_PROPERTY, AMF_VARIANT_INT64, ns)

        cdef AMF_RESULT res = self.encoder.pVtbl.SubmitInput(self.encoder, <AMFData*> self.surface)
        if res == AMF_INPUT_FULL:
            # wait!
            pass
        self.check(res, "AMF submitting input to the encoder")
        cdef AMFData* data = NULL
        for i in range(100):
            res = self.encoder.pVtbl.QueryOutput(self.encoder, &data)
            log(f"QueryOutput()={res}, data=%#x", <uintptr_t> data)
            if res == 0:
                break
            if res == AMF_EOF:
                return b""
            if res == AMF_REPEAT:
                time.sleep(0.001)
                continue
            self.check(res, "AMF query output")
        assert data
        log("data=%s", self.get_data_info(data))
        cdef AMFGuid guid
        set_guid(&guid, 0xb04b7248, 0xb6f0, 0x4321, 0xb6, 0x91, 0xba, 0xa4, 0x74, 0xf, 0x9f, 0xcb)
        cdef AMFBuffer* buffer = NULL
        cdef uint8_t *output = NULL
        cdef size_t size = 0
        try:
            res = data.pVtbl.QueryInterface(data, &guid, <void**> &buffer)
            log(f"QueryInterface()={res}")
            self.check(res, "AMF data query interface")
            assert buffer != NULL
            output = <uint8_t*> buffer.pVtbl.GetNative(buffer)
            size = buffer.pVtbl.GetSize(buffer)
            log(f"output=%#x, size=%i", <uintptr_t> output, size)
            assert output and size
            return output[:size]
        finally:
            if buffer != NULL:
                buffer.pVtbl.Release(buffer)
            data.pVtbl.Release(data)
        return b""

    def flush(self, unsigned long frame_no) -> None:
        cdef AMF_RESULT res = self.encoder.pVtbl.Drain(self.encoder)
        if res == AMF_INPUT_FULL:
            # wait!
            pass
        else:
            self.check(res, "AMF encoder flush")

    cdef get_data_info(self, AMFData *data):
        return {
            "property-count": data.pVtbl.GetPropertyCount(data),
            "memory-type": data.pVtbl.GetMemoryType(data),
            "data-type": data.pVtbl.GetDataType(data),
        }

    cdef get_plane_info(self, AMFPlane *plane):
        return {
            "native": <uintptr_t> plane.pVtbl.GetNative(plane),
            "size": plane.pVtbl.GetPixelSizeInBytes(plane),
            "offset-x": plane.pVtbl.GetOffsetX(plane),
            "offset-y": plane.pVtbl.GetOffsetY(plane),
            "width": plane.pVtbl.GetWidth(plane),
            "height": plane.pVtbl.GetHeight(plane),
            "h-pitch": plane.pVtbl.GetHPitch(plane),
            "v-pitch": plane.pVtbl.GetVPitch(plane),
            "is-tiled": plane.pVtbl.IsTiled(plane),
        }

    def set_encoding_speed(self, int pct) -> None:
        if self.speed==pct:
            return
        self.speed = pct
        self.do_set_encoding_speed(pct)

    cdef void do_set_encoding_speed(self, int speed):
        pass

    def set_encoding_quality(self, int pct) -> None:
        if self.quality==pct:
            return
        self.quality = pct
        self.do_set_encoding_quality(pct)

    cdef void do_set_encoding_quality(self, int pct):
        pass


def selftest(full=False) -> None:
    global CODECS, SAVE_TO_FILE
    from xpra.os_util import WIN32
    if not WIN32:
        raise ImportError("amf encoder needs porting to this platform")
    from xpra.codecs.checks import testencoder, get_encoder_max_size
    from xpra.codecs.amf import encoder
    temp = SAVE_TO_FILE
    try:
        SAVE_TO_FILE = None
        CODECS = testencoder(encoder, full)
    finally:
        SAVE_TO_FILE = temp
