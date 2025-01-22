# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from time import monotonic, sleep
from typing import Any, Dict, Tuple
from collections.abc import Sequence
from ctypes import c_uint64, c_int, c_void_p, byref, POINTER
from ctypes import CDLL

from xpra.codecs.constants import VideoSpec, get_subsampling_divs
from xpra.codecs.image import ImageWrapper
from xpra.os_util import WIN32
from xpra.util.env import envbool, first_time
from xpra.util.objects import AtomicInteger, typedict
from xpra.log import Logger

from libc.stddef cimport wchar_t
from libc.stdint cimport uint8_t, int64_t, uintptr_t
from libc.string cimport memset, memcpy

from xpra.codecs.amf.amf cimport (
    amf_uint8,
    AMF_PLANE_TYPE_STR, AMF_SURFACE_FORMAT_STR, AMF_FRAME_TYPE, AMF_FRAME_TYPE_STR, MEMORY_TYPE_STR,
    AMF_RESULT, AMF_EOF, AMF_REPEAT,
    AMF_DX11_0,
    AMF_MEMORY_TYPE, AMF_MEMORY_DX11, AMF_MEMORY_HOST,
    AMF_INPUT_FULL,
    AMF_SURFACE_FORMAT, AMF_SURFACE_YUV420P, AMF_SURFACE_NV12, AMF_SURFACE_BGRA,
    AMF_VARIANT_TYPE, AMF_VARIANT_INT64, AMF_VARIANT_SIZE, AMF_VARIANT_RATE,
    AMF_VIDEO_ENCODER_USAGE_ENUM,
    AMF_VIDEO_ENCODER_USAGE_ULTRA_LOW_LATENCY,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_ENUM,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_QUALITY,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_SPEED,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_BALANCED,
    AMF_VIDEO_ENCODER_AV1_LEVEL_5_1,
    AMF_VIDEO_ENCODER_AV1_PROFILE_MAIN,
    AMF_VIDEO_ENCODER_AV1_USAGE_ULTRA_LOW_LATENCY,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_ENUM,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_HIGH_QUALITY,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_QUALITY,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_SPEED,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_BALANCED,
    AMF_VIDEO_ENCODER_HEVC_USAGE_ENUM,
    AMF_VIDEO_ENCODER_HEVC_USAGE_ULTRA_LOW_LATENCY,
    AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_ENUM,
    AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_QUALITY,
    AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED,
    AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_BALANCED,
    amf_handle, amf_long, amf_int32,
    AMFDataAllocatorCB,
    AMFSize, AMFRate,
    AMFGuid,
    AMFBuffer,
    AMFComponentOptimizationCallback,
    AMFPlane, AMFPlaneVtbl,
    AMFData, AMFDataVtbl,
    AMFTrace,
    AMFVariantStruct, AMFVariantInit,
    AMFVariantAssignInt64, AMFVariantAssignSize, AMFVariantAssignRate,
    AMFSurface, AMFSurfaceVtbl,
    AMFContext,
    AMFComponent,
    AMFFactory,
)
from xpra.codecs.amf.common cimport (
    set_guid, get_factory, get_version, check,
)


log = Logger("encoder", "amf")

DX11 = envbool("XPRA_AMF_DX11", WIN32)
SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")


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
    # cdef extern from "pymem.h":
    void PyMem_Free(void *ptr)


def init_module() -> None:
    get_factory()

def cleanup_module() -> None:
    log("amf.encoder.cleanup_module()")


cdef inline AMF_VIDEO_ENCODER_QUALITY_PRESET_ENUM get_h264_preset(int quality, int speed):
    if quality >= 80:
        return AMF_VIDEO_ENCODER_QUALITY_PRESET_QUALITY
    if speed >= 80:
        return AMF_VIDEO_ENCODER_QUALITY_PRESET_SPEED
    return AMF_VIDEO_ENCODER_QUALITY_PRESET_BALANCED


cdef inline AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_ENUM get_av1_preset(int quality, int speed):
    if quality >= 90:
        return AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_HIGH_QUALITY
    if quality >= 90:
        return AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_QUALITY
    if speed >= 80:
        return AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_SPEED
    return AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_BALANCED


cdef inline AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_ENUM get_hevc_preset(int quality, int speed):
    if quality >= 80:
        return AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_QUALITY
    if speed >= 80:
        return AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED
    return AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_BALANCED


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


generation = AtomicInteger()


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
    cdef unsigned int generation
    cdef object file

    cdef object __weakref__

    def init_context(self, encoding: str,
                     unsigned int width, unsigned int height,
                     src_format: str,
                     options: typedict) -> None:
        log(f"amf init_context%s {SAVE_TO_FILE=}", (encoding, width, height, src_format, options))
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
        self.device = NULL

        self.amf_context_init()
        self.amf_encoder_init(options)

        self.generation = generation.increase()
        if SAVE_TO_FILE:
            filename = SAVE_TO_FILE+f"amf-{self.generation}.{encoding}"
            self.file = open(filename, "wb")
            log.info(f"saving {encoding} stream to {filename!r}")

    def check(self, res: AMF_RESULT, message: str):
        if res:
            check(res, message)
            self.clean()

    def amf_context_init(self) -> None:
        cdef AMFFactory *factory = get_factory()
        cdef AMF_RESULT res = factory.pVtbl.CreateContext(factory, &self.context)
        log(f"amf_context_init() CreateContext()={res}")
        self.check(res, "AMF context initialization")
        if DX11:
            res = self.context.pVtbl.InitDX11(self.context, NULL, AMF_DX11_0)
            log(f"amf_context_init() InitDX11()={res}")
            self.check(res, "AMF DX11 device initialization")
            self.device = self.context.pVtbl.GetDX11Device(self.context, AMF_DX11_0)
            assert self.device
            from xpra.platform.win32.d3d11.device import D3D11Device
            device = D3D11Device(<uintptr_t> self.device)
            device_info = device.get_info()
            log("device: %s", device_info)
            descr = device_info.get("description", "")
            if descr and first_time(f"GPU:{descr}"):
                log.info(f"AMF initialized using DX11 device {descr!r}")
        else:
            res = self.context.pVtbl.InitOpenGL(self.context, NULL, NULL, NULL)
            log(f"amf_context_init() InitOpenGL()={res}")
            self.check(res, "AMF OpenGL device initialization")
            self.device = <void *> self.context.pVtbl.GetOpenGLContext(self.context)
        log(f"amf_context_init() device=%#x", <uintptr_t> self.device)

    cdef void set_encoder_property(self, name: str, AMFVariantStruct var):
        cdef wchar_t *prop = PyUnicode_AsWideCharString(name, NULL)
        ret = self.encoder.pVtbl.SetProperty(self.encoder, prop, var)
        self.check(ret, f"AMF encoder setting property {name} to {var!r}")
        PyMem_Free(prop)

    def amf_encoder_init(self, options: typedict) -> None:
        cdef AMFFactory *factory = get_factory()
        assert factory and self.context
        log(f"amf_encoder_init() for encoding {self.encoding!r}")

        amf_codec_name = str(AMF_ENCODINGS[self.encoding])
        cdef wchar_t *amf_codec = PyUnicode_AsWideCharString(amf_codec_name, NULL)
        cdef AMF_RESULT res = get_factory().pVtbl.CreateComponent(factory, self.context, amf_codec, &self.encoder)
        PyMem_Free(amf_codec)
        log(f"amf_encoder_init() CreateComponent()={res}")
        self.check(res, f"AMF {self.encoding!r} encoder creation")

        speed = options.intget("speed", 50)
        quality = options.intget("quality", 50)
        bwlimit = options.intget("bandwidth-limit", 0)

        cdef AMFVariantStruct var
        cdef AMFSize size
        cdef AMFRate rate
        def setint64(prop: str, value: int) -> None:
            self.check(AMFVariantInit(&var), "AMF variant initialization")
            AMFVariantAssignInt64(&var, value)
            self.set_encoder_property(prop, var)
        def setsize(prop: str) -> None:
            self.check(AMFVariantInit(&var), "AMF variant initialization")
            var.type = AMF_VARIANT_SIZE
            var.sizeValue.width = self.width
            var.sizeValue.height = self.height
            self.set_encoder_property(prop, var)
        def setframerate(prop: str) -> None:
            self.check(AMFVariantInit(&var), "AMF variant initialization")
            var.type = AMF_VARIANT_RATE
            var.rateValue.num = 25
            var.rateValue.den = 1
            self.set_encoder_property(prop, var)
        def setbitrate(prop: str) -> None:
            if bwlimit:
                setint64(prop, value=bwlimit)

        # tune encoder:
        if self.encoding == "h264":
            setsize("FrameSize")
            setframerate("FrameRate")
            setbitrate("TargetBitrate")
            setint64("Usage", value=AMF_VIDEO_ENCODER_USAGE_ULTRA_LOW_LATENCY)
            setint64("QualityPreset", get_h264_preset(quality, speed))
            if False:
                setint64("Profile", value=AMF_VIDEO_ENCODER_PROFILE_HIGH)
                setint64("ProfileLevel", value=AMF_H264_LEVEL__5_1)
            if not options.boolget("b-frames", False):
                setint64("BPicturesPattern", value=0)
                # can be not supported - check Capability Manager sample
        elif self.encoding == "av1":
            setsize("Av1FrameSize")
            setframerate("Av1FrameRate")
            setbitrate("Av1TargetBitrate")
            setint64("Av1Usage", value=AMF_VIDEO_ENCODER_AV1_USAGE_ULTRA_LOW_LATENCY)
            setint64("Av1QualityPreset", get_av1_preset(quality, speed))
            setint64("Av1Profile", AMF_VIDEO_ENCODER_AV1_PROFILE_MAIN)
            setint64("Av1Level", AMF_VIDEO_ENCODER_AV1_LEVEL_5_1)
            if False:
                setint64("Av1AlignmentMode", AMF_VIDEO_ENCODER_AV1_ALIGNMENT_MODE_NO_RESTRICTIONS)
        elif self.encoding == "hevc":
            setint64("HevcUsage", AMF_VIDEO_ENCODER_HEVC_USAGE_ULTRA_LOW_LATENCY)
            setint64("HevcQualityPreset", get_hevc_preset(quality, speed))
            setsize("HevcFrameSize")
            setframerate("HevcFrameRate")
            setbitrate("HevcTargetBitrate")
            # setint64(AMF_VIDEO_ENCODER_HEVC_TIER, AMF_VIDEO_ENCODER_HEVC_TIER_HIGH)
            # setint64(AMF_VIDEO_ENCODER_HEVC_PROFILE_LEVEL, AMF_LEVEL_5_1)
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
            return self.do_compress_image(pic_in, strides), {
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

    cdef void alloc_surface(self, AMFSurface **surface, AMF_MEMORY_TYPE memory=AMF_MEMORY_HOST):
        assert self.context
        memtype = MEMORY_TYPE_STR(memory)
        cdef AMF_RESULT res = self.context.pVtbl.AllocSurface(self.context, memory, self.surface_format,
                                                             self.width, self.height, surface)
        if res:
            self.check(res, f"AMF {memtype} surface initialization for {self.width}x{self.height} {self.src_format}")
        cdef AMFSurface *ptr = surface[0]
        assert ptr != NULL
        log(f"{memtype} surface: %s", self.get_surface_info(ptr))

    cdef void set_surface_property(self, AMFSurface *surface, name: str, variant: AMF_VARIANT_TYPE, value: int64_t):
        cdef AMFVariantStruct var
        AMFVariantAssignInt64(&var, value)
        cdef wchar_t *prop = PyUnicode_AsWideCharString(name, NULL)
        surface.pVtbl.SetProperty(surface, prop, var)
        PyMem_Free(prop)

    cdef uintptr_t get_native_plane(self, AMFSurface *surface, unsigned int plane_index):
        # get the D3D11 host destination surface pointer for this plane:
        plane = surface.pVtbl.GetPlaneAt(surface, plane_index)
        assert plane
        log("plane=%s", self.get_plane_info(plane))
        # texture is a `ID3D11Texture2D`:
        cdef uintptr_t texture = <uintptr_t> plane.pVtbl.GetNative(plane)
        assert texture
        return texture

    cdef bytes do_compress_image(self, uint8_t *pic_in[2], int strides[2]):
        cdef unsigned long start_time = 0    # nanoseconds!
        cdef AMFPlane *plane
        cdef uintptr_t host_texture
        cdef uintptr_t gpu_texture
        cdef AMFSurface *host_surface
        cdef AMFSurface *gpu_surface
        cdef AMF_RESULT res

        if not WIN32:
            raise ImportError("amf encoder needs porting to this platform")

        from xpra.platform.win32.d3d11.device import D3D11Device
        log("D3D11Device(%#x)", <uintptr_t> self.device)
        device = D3D11Device(<uintptr_t> self.device)
        with device.get_device_context() as dc:
            log("device: %s", device.get_info())
            log("device context: %s", dc.get_info())

            self.alloc_surface(&host_surface, AMF_MEMORY_HOST)

            for plane_index in range(2):
                log("plane %s src data=%#x", ["Y", "UV"][plane_index], <uintptr_t> pic_in[plane_index])
                host_texture = self.get_native_plane(host_surface, plane_index)
                memcpy(<void *> host_texture, <void *> pic_in[plane_index], strides[plane_index] * (self.height//2))

            # make it accessible by the GPU:
            res = host_surface.pVtbl.Convert(host_surface, AMF_MEMORY_DX11)
            self.check(res, "AMF Convert to DX11 memory")

            self.alloc_surface(&gpu_surface, AMF_MEMORY_DX11)

            for plane_index in range(2):
                log("plane %s", ["Y", "UV"][plane_index])
                host_texture = self.get_native_plane(host_surface, plane_index)
                gpu_texture = self.get_native_plane(gpu_surface, plane_index)
                dc.copy_resource(gpu_texture, host_texture)
            log("flush()")
            dc.flush()
            log("freeing host surface=%s", <uintptr_t> host_surface)
            host_surface.pVtbl.Release(host_surface)

        ns = round(1000 * 1000 * monotonic())
        self.set_surface_property(gpu_surface, START_TIME_PROPERTY, AMF_VARIANT_INT64, ns)

        log("encoder.SubmitInput()")
        res = self.encoder.pVtbl.SubmitInput(self.encoder, <AMFData*> gpu_surface)
        gpu_surface.pVtbl.Release(gpu_surface)
        if res == AMF_INPUT_FULL:
            raise RuntimeError("AMF encoder input is full!")
        self.check(res, "AMF submitting input to the encoder")
        cdef AMFData* data = NULL
        for i in range(200):
            res = self.encoder.pVtbl.QueryOutput(self.encoder, &data)
            log(f"QueryOutput()={res}, data=%#x", <uintptr_t> data)
            if res == 0:
                break
            if res == AMF_EOF:
                return b""
            if res == AMF_REPEAT:
                sleep(0.001)
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
            log(f"QueryInterface()={res} AMFBuffer=%#x", <uintptr_t> buffer)
            self.check(res, "AMF data query interface")
            assert buffer != NULL
            output = <uint8_t*> buffer.pVtbl.GetNative(buffer)
            size = buffer.pVtbl.GetSize(buffer)
            log(f"output=%#x, size=%i", <uintptr_t> output, size)
            assert output and size
            bdata = output[:size]
            if self.file:
                self.file.write(bdata)
            return bdata
        finally:
            if buffer != NULL:
                buffer.pVtbl.Release(buffer)
            data.pVtbl.Release(data)

    def flush(self, unsigned long frame_no) -> None:
        cdef AMF_RESULT res
        for _ in range(200):
            res = self.encoder.pVtbl.Drain(self.encoder)
            if res != AMF_INPUT_FULL:
                break
            sleep(0.001)
        self.check(res, "AMF encoder flush")

    cdef get_data_info(self, AMFData *data):
        assert data
        cdef const AMFDataVtbl *dfn = data.pVtbl
        return {
            "property-count": dfn.GetPropertyCount(data),
            "memory-type": dfn.GetMemoryType(data),
            "data-type": dfn.GetDataType(data),
        }

    cdef get_plane_info(self, AMFPlane *plane):
        assert plane
        ptype = plane.pVtbl.GetType(plane)
        cdef const AMFPlaneVtbl *pfn = plane.pVtbl
        return {
            "type": AMF_PLANE_TYPE_STR(ptype),
            "native": <uintptr_t> pfn.GetNative(plane),
            "size": pfn.GetPixelSizeInBytes(plane),
            "offset-x": pfn.GetOffsetX(plane),
            "offset-y": pfn.GetOffsetY(plane),
            "width": pfn.GetWidth(plane),
            "height": pfn.GetHeight(plane),
            "h-pitch": pfn.GetHPitch(plane),
            "v-pitch": pfn.GetVPitch(plane),
            "is-tiled": pfn.IsTiled(plane),
        }

    cdef get_surface_info(self, AMFSurface *surface):
        assert surface
        cdef const AMFSurfaceVtbl *sfn = surface.pVtbl
        fmt = sfn.GetFormat(surface)
        cdef AMF_FRAME_TYPE ftype = sfn.GetFrameType(surface)
        return {
            "format": AMF_SURFACE_FORMAT_STR(fmt),
            "planes": sfn.GetPlanesCount(surface),
            "frame-type": AMF_FRAME_TYPE_STR(ftype),
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
