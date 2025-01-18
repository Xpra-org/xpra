# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import math

from collections import deque
from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.log import Logger
log = Logger("encoder", "amf")

from xpra.codecs.constants import VideoSpec, get_subsampling_divs
from xpra.codecs.image import ImageWrapper
from xpra.os_util import WIN32, OSX, POSIX
from xpra.util.env import envint, envbool
from xpra.util.objects import typedict

from libc.stddef cimport wchar_t
from libc.stdint cimport uint8_t, uint64_t, uintptr_t
from libc.stdlib cimport free, malloc
from libc.string cimport memset

from xpra.codecs.amf.amf cimport (
    AMF_RESULT,
    amf_handle, amf_long,
    amf_int32,
    AMFDataAllocatorCB,
    AMFComponentOptimizationCallback,
    AMF_DX11_0,
    AMF_MEMORY_TYPE,
    AMF_MEMORY_DX11,
    AMF_SURFACE_FORMAT, AMF_SURFACE_YUV420P, AMF_SURFACE_NV12, AMF_SURFACE_BGRA,
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

DX11 = envbool("XPRA_AMF_DX11", True)
SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")

AMF_DLL_NAME = "amfrt64.dll" if WIN32 else "libamf.so"


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS
    # cdef extern from "unicodeobject.h":
    wchar_t* PyUnicode_AsWideCharString(object unicode, Py_ssize_t *size)
    # cdef extern from "pymem.h":
    void PyMem_Free(void *ptr)


AMF_ENCODINGS : Dict[str, str] = {
    "hevc": "AMFVideoEncoder_HEVC",
    "av1": "AMFVideoEncoder_AV1",
}


cdef AMFFactory *factory = NULL


def init_module() -> None:
    log("amf.encoder.init_module() info=%s", get_info())
    version = get_c_version()
    res = AMFInit(version, <uintptr_t> &factory)
    log(f"AMFInit: {res=}, factory=%s", <uintptr_t> factory)
    if res:
        raise RuntimeError(f"AMF initialization failed and returned {res}")


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


def get_version() -> Sequence[int]:
    version = get_c_version()
    return version >> 48, (version >> 32) & 0xffff, (version >> 16) & 0xffff, version & 0xffff


def get_type() -> str:
    return "amf"


CODECS = tuple(AMF_ENCODINGS.keys())

def get_encodings() -> Sequence[str]:
    return CODECS


def get_input_colorspaces(encoding: str):
    assert encoding in get_encodings(), "invalid encoding: %s" % encoding
    # return ("YUV420P", "NV12", "BGRA")
    return ("BGRA", )


def get_output_colorspaces(encoding: str, input_colorspace: str):
    assert encoding in get_encodings(), "invalid encoding: %s" % encoding
    assert input_colorspace in get_input_colorspaces(encoding)
    return ("YUV420P", )


def get_info() -> Dict[str,Any]:
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
    cdef void *device_context
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

        self.amf_context_init()
        self.amf_encoder_init()
        self.amf_surface_init()

        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+f"amf-{self.generation}.{encoding}"
            self.file = open(filename, "wb")
            log.info(f"saving {encoding} stream to {filename!r}")

    cdef amf_context_init(self):
        assert factory
        cdef AMF_RESULT res = factory.pVtbl.CreateContext(factory, &self.context)
        log(f"amf_context_init() CreateContext()={res}")
        if res:
            raise RuntimeError(f"AMF context initialization failed and returned {res}")
        if DX11:
            res = self.context.pVtbl.InitDX11(self.context, NULL, AMF_DX11_0)
            log(f"amf_context_init() InitDX11()={res}")
            if res:
                raise RuntimeError(f"AMF DX11 device initialization failed and returned {res}")
            self.device_context = self.context.pVtbl.GetDX11Device(self.context, AMF_DX11_0)
        else:
            res = self.context.pVtbl.InitOpenGL(self.context, 0, 0, 0)
            log(f"amf_context_init() InitOpenGL()={res}")
            if res:
                raise RuntimeError(f"AMF OpenGL device initialization failed and returned {res}")
            self.device_context = <void *> self.context.pVtbl.GetOpenGLContext(self.context)

    cdef amf_encoder_init(self):
        assert factory and self.context
        log(f"amf_encoder_init() for encoding={self.encoding}")

        amf_codec_name = str(AMF_ENCODINGS[self.encoding])
        cdef wchar_t *amf_codec = PyUnicode_AsWideCharString(amf_codec_name, NULL)
        cdef AMF_RESULT res = factory.pVtbl.CreateComponent(factory, self.context, amf_codec, &self.encoder)
        PyMem_Free(amf_codec)
        log(f"amf_encoder_init() CreateComponent()={res}")
        if not res:
            raise RuntimeError(f"AMF failed to create {self.encoding!r} encoder and returned {res}")

        # tune encoder:
        if self.encoding == "AV1":
            pass
        elif self.encoding == "HEVC":
            pass
        else:
            raise RuntimeError("unexpected encoding {self.encoding!r}")

        # init:
        res = self.encoder.pVtbl.Init(self.encoder, self.surface_format, self.width, self.height)
        if not res:
            raise RuntimeError(f"AMF failed to initialize {self.encoding!r} {self.width}x{self.height} {self.src_format} encoder context and returned {res}")

    cdef amf_surface_init(self):
        log("amf_surface_init()")
        assert DX11
        cdef AMF_MEMORY_TYPE memory = AMF_MEMORY_DX11

        cdef AMF_RESULT res = self.context.pVtbl.AllocSurface(self.context, memory, self.surface_format, self.width, self.height, &self.surface)
        if res:
            raise RuntimeError(f"AMF failed to initialize surface {self.width}x{self.height} {self.src_format} and returned {res}")

    def is_ready(self) -> bool:
        return True

    def __repr__(self):
        return "amf.Encoder(%s)" % self.encoding

    def get_info(self) -> Dict[str,Any]:
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
        cdef AMFSurface* surface = self.surface
        if surface:
            self.surface = NULL
            surface.pVtbl.Release(surface)
        cdef AMFComponent* encoder = self.encoder
        if encoder:
            self.encoder = NULL
            encoder.pVtbl.Terminate(encoder)
            encoder.pVtbl.Release(encoder)
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
        cdef uint8_t *pic_in[3]
        cdef int strides[3]
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
        assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
        assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
        divs = get_subsampling_divs(self.src_format)

        cdef int speed = options.intget("speed", 50)
        if speed>=0:
            self.set_encoding_speed(speed)
        cdef int quality = options.intget("quality", 50)
        if quality>=0:
            self.set_encoding_quality(quality)

        cdef Py_buffer py_buf[3]
        for i in range(3):
            memset(&py_buf[i], 0, sizeof(Py_buffer))
        try:
            for i in range(3):
                xdiv, ydiv = divs[i]
                if PyObject_GetBuffer(pixels[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                    raise ValueError(f"failed to read pixel data from {type(pixels[i])}")
                assert istrides[i]>=self.width*4//xdiv, "invalid stride %i for width %i" % (istrides[i], self.width)
                assert py_buf[i].len>=istrides[i]*(self.height//ydiv), "invalid buffer length %i for plane %s, at least %i needed" % (
                    py_buf[i].len, "YUV"[i], istrides[i]*(self.height//ydiv))
                pic_in[i] = <uint8_t *> py_buf[i].buf
                strides[i] = istrides[i]
            return self.do_compress_image(pic_in, strides, full_range), {
                "csc"       : self.src_format,
                "frame"     : int(self.frames),
                "full-range" : bool(full_range),
                #"quality"  : min(99+self.lossless, self.quality),
                #"speed"    : self.speed,
            }
        finally:
            for i in range(3):
                if py_buf[i].buf:
                    PyBuffer_Release(&py_buf[i])

    cdef bytes do_compress_image(self, uint8_t *pic_in[3], int strides[3], int full_range):
        return b""

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
