# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from time import monotonic, sleep
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec, get_subsampling_divs, EncodingNotSupported, is_screen_content
from xpra.codecs.image import ImageWrapper
from xpra.os_util import WIN32
from xpra.util.env import envbool, envint, first_time
from xpra.util.objects import AtomicInteger, typedict
from xpra.log import Logger

from libc.stddef cimport wchar_t
from libc.stdint cimport uint8_t, int64_t, uintptr_t
from libc.string cimport memset, memcpy

from xpra.codecs.amf.amf cimport (
    MEMORY_TYPE_STR,
    AMF_RESULT, AMF_EOF, AMF_REPEAT,
    AMF_DX11_0,
    AMF_MEMORY_TYPE, AMF_MEMORY_DX11, AMF_MEMORY_HOST,
    AMF_INPUT_FULL, AMF_NOT_SUPPORTED, AMF_ALREADY_INITIALIZED, AMF_OK,
    AMF_SURFACE_FORMAT, AMF_SURFACE_YUV420P, AMF_SURFACE_NV12, AMF_SURFACE_BGRA,
    AMF_VARIANT_TYPE, AMF_VARIANT_INT64, AMF_VARIANT_SIZE, AMF_VARIANT_RATE,
    AMF_VIDEO_ENCODER_USAGE_LOW_LATENCY,
    AMF_VIDEO_ENCODER_USAGE_ULTRA_LOW_LATENCY,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_ENUM,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_QUALITY,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_SPEED,
    AMF_VIDEO_ENCODER_QUALITY_PRESET_BALANCED,
    AMF_VIDEO_ENCODER_RATE_CONTROL_METHOD_CONSTANT_QP,
    AMF_VIDEO_ENCODER_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR,
    AMF_VIDEO_ENCODER_AV1_LEVEL_5_1,
    AMF_VIDEO_ENCODER_AV1_PROFILE_MAIN,
    AMF_VIDEO_ENCODER_AV1_USAGE_ULTRA_LOW_LATENCY,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_ENUM,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_HIGH_QUALITY,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_QUALITY,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_SPEED,
    AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_BALANCED,
    AMF_VIDEO_ENCODER_AV1_RATE_CONTROL_METHOD_CONSTANT_QP,
    AMF_VIDEO_ENCODER_AV1_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR,
    AMF_VIDEO_ENCODER_HEVC_USAGE_ULTRA_LOW_LATENCY,
    AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_ENUM,
    AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_QUALITY,
    AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED,
    AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_BALANCED,
    AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_CONSTANT_QP,
    AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR,
    amf_int32,
    AMFSize, AMFRate,
    AMFCaps,
    AMFGuid,
    AMFBuffer,
    AMFPlane,
    AMFData,
    AMFVariantStruct, AMFVariantInit,
    AMFVariantAssignInt64,
    AMFSurface,
    AMFContext, AMFContext1,
    AMFComponent,
    AMFFactory,
)
from xpra.codecs.amf.common cimport (
    set_guid, get_factory, get_version, check, error_str,
    get_caps, get_plane_info, get_data_info, get_surface_info,
)


log = Logger("encoder", "amf")

DX11 = envbool("XPRA_AMF_DX11", WIN32)
SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE", "")


AMF_ENCODINGS : Dict[str, str] = {
    # AMFVideoEncoderVCE_SVC?
    "h264": "AMFVideoEncoderVCE_AVC",
    "hevc": "AMFVideoEncoder_HEVC",
    "av1": "AMFVideoEncoder_AV1",
}

START_TIME_PROPERTY = "StartTimeProperty"


# The three encoders expose the same knobs under three different names, so keep the
# mapping in one place rather than repeating each `SetProperty` call per codec.
# A knob that is missing from a table simply is not applied for that codec.
PROPERTIES: Dict[str, Dict[str, str]] = {
    "h264": {
        "usage": "Usage",
        "quality-preset": "QualityPreset",
        "frame-size": "FrameSize",
        "frame-rate": "FrameRate",
        "rate-control": "RateControlMethod",
        "target-bitrate": "TargetBitrate",
        "peak-bitrate": "PeakBitrate",
        "qp-intra": "QPI",
        "qp-inter": "QPP",
        "gop-size": "IDRPeriod",
        "b-frames": "BPicturesPattern",
        "query-timeout": "QueryTimeout",
        "deblocking": "DeBlockingFilter",
    },
    "hevc": {
        # two knobs are deliberately missing here, both because there is no HEVC capable
        # hardware to verify them against:
        # * "deblocking": the HEVC property of the same name has the opposite polarity
        #   (`AMF_VIDEO_ENCODER_HEVC_DE_BLOCKING_FILTER_DISABLE`)
        # * "gop-size": AMF documents `Av1GOPSize` = 0 as "key frame at the first frame
        #   only" and `IDRPeriod` = 0 behaves the same way, but `HevcGOPSize` says
        #   nothing about 0, and guessing wrong would make every frame an intra frame.
        #   HEVC therefore keeps its default GOP of 60 frames for now.
        "usage": "HevcUsage",
        "quality-preset": "HevcQualityPreset",
        "frame-size": "HevcFrameSize",
        "frame-rate": "HevcFrameRate",
        "rate-control": "HevcRateControlMethod",
        "target-bitrate": "HevcTargetBitrate",
        "peak-bitrate": "HevcPeakBitrate",
        "qp-intra": "HevcQP_I",
        "qp-inter": "HevcQP_P",
        "query-timeout": "HevcQueryTimeout",
    },
    "av1": {
        "usage": "Av1Usage",
        "quality-preset": "Av1QualityPreset",
        "frame-size": "Av1FrameSize",
        "frame-rate": "Av1FrameRate",
        "rate-control": "Av1RateControlMethod",
        "target-bitrate": "Av1TargetBitrate",
        "peak-bitrate": "Av1PeakBitrate",
        # AV1 quantizes on a 1..255 `QIndex` scale rather than 0..51:
        "qp-intra": "Av1QIndex_Intra",
        "qp-inter": "Av1QIndex_Inter",
        "gop-size": "Av1GOPSize",
        "query-timeout": "Av1QueryTimeout",
        "screen-content": "Av1ScreenContentTools",
        "palette-mode": "Av1PaletteMode",
    },
}

# `Usage` is a preset: it configures the whole rate control parameter set in one go.
# It must be the *first* property we set, since it overwrites anything set before it:
USAGE: Dict[str, int] = {
    "h264": AMF_VIDEO_ENCODER_USAGE_ULTRA_LOW_LATENCY,
    "hevc": AMF_VIDEO_ENCODER_HEVC_USAGE_ULTRA_LOW_LATENCY,
    "av1": AMF_VIDEO_ENCODER_AV1_USAGE_ULTRA_LOW_LATENCY,
}

CONSTANT_QP: Dict[str, int] = {
    "h264": AMF_VIDEO_ENCODER_RATE_CONTROL_METHOD_CONSTANT_QP,
    "hevc": AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_CONSTANT_QP,
    "av1": AMF_VIDEO_ENCODER_AV1_RATE_CONTROL_METHOD_CONSTANT_QP,
}

PEAK_CONSTRAINED_VBR: Dict[str, int] = {
    "h264": AMF_VIDEO_ENCODER_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR,
    "hevc": AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR,
    "av1": AMF_VIDEO_ENCODER_AV1_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR,
}

# the enum values are not in the same order for all three codecs
# (h264 has CBR at 1, hevc and av1 have it at 3):
RATE_CONTROL_STR: Dict[str, Dict[int, str]] = {
    "h264": {
        0: "constant-qp", 1: "cbr", 2: "peak-constrained-vbr", 3: "latency-constrained-vbr",
        4: "quality-vbr", 5: "high-quality-vbr", 6: "high-quality-cbr",
    },
}
RATE_CONTROL_STR["hevc"] = RATE_CONTROL_STR["av1"] = {
    0: "constant-qp", 1: "latency-constrained-vbr", 2: "peak-constrained-vbr", 3: "cbr",
    4: "quality-vbr", 5: "high-quality-vbr", 6: "high-quality-cbr",
}

# how long `QueryOutput` may block in the driver waiting for an encoded frame.
# without it, AMF returns `AMF_REPEAT` straight away and we poll from python:
QUERY_TIMEOUT = envint("XPRA_AMF_QUERY_TIMEOUT", 200)


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS
    # cdef extern from "unicodeobject.h":
    wchar_t* PyUnicode_AsWideCharString(object unicode, Py_ssize_t *size)
    # cdef extern from "pymem.h":
    void PyMem_Free(void *ptr)


cdef inline AMF_VIDEO_ENCODER_QUALITY_PRESET_ENUM get_h264_preset(int quality, int speed):
    if quality >= 80:
        return AMF_VIDEO_ENCODER_QUALITY_PRESET_QUALITY
    if speed >= 80:
        return AMF_VIDEO_ENCODER_QUALITY_PRESET_SPEED
    return AMF_VIDEO_ENCODER_QUALITY_PRESET_BALANCED


cdef inline AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_ENUM get_av1_preset(int quality, int speed):
    if quality >= 90:
        return AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_HIGH_QUALITY
    if quality >= 80:
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


# The AVC and HEVC quantizers both run from 0 to 51, and AV1 uses a `QIndex` on a
# 1..255 scale instead, which is roughly four steps per QP step.
# The top of the QP range is not worth having: past QP 42 the reference picture is
# degraded enough that inter prediction starts to fail, and the frames get *bigger*
# again. Measured over 40 frames of 1280x720 at a fixed QP:
#   QP     40      42      44      46      48      51
#   text   1184B   1106B   1134B   1233B   1424B   1511B   (33.1 .. 24.4 dB)
#   video  3258B   3407B   4584B   6176B   6144B   5604B   (35.1 .. 26.6 dB)
# ie: QP 51 costs 37% more bytes than QP 42 on text and is 7dB worse, so there is
# nothing to gain by ever asking for it.
MIN_QP = envint("XPRA_AMF_MIN_QP", 0)
MAX_QP = envint("XPRA_AMF_MAX_QP", 42)


def get_qp(int quality) -> int:
    # higher quality -> lower QP:
    quality = max(0, min(100, quality))
    return MAX_QP - (quality * (MAX_QP - MIN_QP)) // 100


def get_qindex(int quality) -> int:
    return max(1, min(255, get_qp(quality) * 4))


def get_type() -> str:
    return "amf"


CODECS = tuple(AMF_ENCODINGS.keys())


def get_encodings() -> Sequence[str]:
    return CODECS


def get_info() -> Dict[str, Any]:
    info = {
        "version"       : get_version(),
        "encodings"     : get_encodings(),
    }
    return info


def get_specs() -> Sequence[VideoSpec]:
    specs: Sequence[VideoSpec] = []
    speed = 50
    quality = 50
    for encoding in CODECS:
        caps = CAPS.get(encoding, {})
        input_caps = caps.get("input", {})
        output_caps = caps.get("output", {})
        min_w, max_w = input_caps.get("width-range", (128, 4096))
        min_h, max_h = input_caps.get("height-range", (128, 4096))
        input_colorspaces = input_caps.get("native-formats", ("NV12", ))
        output_colorspaces = output_caps.get("native-formats", ("YUV420P", ))
        for input_colorspace in input_colorspaces:
            # ugly translation into the names xpra uses for legacy reasons:
            out_css = tuple({"NV12" : "YUV420P"}.get(cs, cs) for cs in output_colorspaces)
            spec = VideoSpec(
                encoding=encoding, input_colorspace=input_colorspace, output_colorspaces=out_css,
                has_lossless_mode=False,
                full_range=False,
                codec_class=Encoder, codec_type=get_type(),
                quality=quality, speed=speed,
                size_efficiency=60,
                setup_cost=20,
                min_w=min_w, min_h=min_h,
                max_w=max_w, max_h=max_h)
            log("AMF encoder spec for %r: %s", encoding, spec.to_dict())
            specs.append(spec)
    return specs


# these are the actual caps and are probed during the self-tests:
CAPS: Dict[str, str] = {}


ENCODING_CAPS: Dict[str, Dict[str, str]] = {
    "h264": {
        "max-bitrate" : "MaxBitrate",
        "number-of-streams": "NumOfStreams",
        "max-level": "MaxLevel",
        "b-frames": "BFrames",
        "max-throughput": "MaxThroughput",
        "fixed-sliced-mode": "FixedSliceMode",
        "color-conversion": "ColorConversion",
        "hardware-instances": "NumOfHwInstances",
        "requested-throughput": "RequestedThroughput",
        "roi": "ROIMap",
        "pre-analysis": "PreAnalysis",
    },
    "av1": {
        # "number-of-streams": n/a
        "max-level": "Av1MaxLevel",
        "max-profile": "Av1MaxProfile",
        "hardware-instances": "Av1CapNumOfHwInstances",
        "max-throughput": "Av1CapMaxThroughput",
        "max-bitrate": "Av1MaxBitrate",
        "requested-throughput": "Av1CapRequestedThroughput",
        # "roi": n/a,
        "pre-analysis": "Av1PreAnalysis",
        "tile-output": "AV1SupportTileOutput",
        "width-alignment": "Av1WidthAlignmentFactor",
        "height-alignment": "Av1HeightAlignmentFactor",
    },
    "hevc": {
        "max-bitrate" : "HevcMaxBitrate",
        "number-of-streams": "HevcNumOfStreams",
        "max-profile": "HevcMaxProfile",
        "max-tier": "HevcMaxTier",
        "max-level": "HevcMaxLevel",
        "hardware-instances": "HevcNumOfHwInstances",
        "max-throughput": "HevcMaxThroughput",
        "requested-throughput": "HevcRequestedThroughput",
        "pre-analysis": "HevcPreAnalysis",
    },
}


generation = AtomicInteger()


cdef class Encoder:
    cdef AMFContext *context
    cdef AMFContext1 *context1
    cdef AMFComponent* encoder
    cdef AMF_SURFACE_FORMAT surface_format
    cdef AMFSurface* surface
    cdef void *device
    cdef object device_info
    cdef unsigned long frames
    cdef unsigned int width
    cdef unsigned int height
    cdef object encoding
    cdef object src_format
    cdef int speed
    cdef int quality
    cdef int rate_control
    cdef int query_timeout
    cdef object content_types
    cdef unsigned int generation
    cdef object file
    cdef object caps

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
        assert src_format == "NV12", f"invalid source format {src_format!r} for {encoding!r}"
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
        self.content_types = options.strtupleget("content-types", ())
        self.rate_control = -1
        self.query_timeout = 0
        self.frames = 0

        self.context = NULL
        self.encoder = NULL
        self.device = NULL
        self.caps = {}
        self.device_info = {}

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
        cdef AMFGuid amf1contextguid
        if DX11:
            res = self.context.pVtbl.InitDX11(self.context, NULL, AMF_DX11_0)
            log(f"amf_context_init() InitDX11()={res}")
            self.check(res, "AMF DX11 device initialization")
            self.device = self.context.pVtbl.GetDX11Device(self.context, AMF_DX11_0)
            assert self.device
            from xpra.platform.win32.d3d11.device import D3D11Device
            device = D3D11Device(<uintptr_t> self.device)
            self.device_info = device.get_info()
            log("device: %s", self.device_info)
            descr = self.device_info.get("description", "")
            if descr and first_time(f"GPU:{descr}"):
                log.info(f"AMF initialized using DX11 device {descr!r}")
        else:
            set_guid(&amf1contextguid, 0xd9e9f868, 0x6220, 0x44c6, 0xa2, 0x2f, 0x7c, 0xd6, 0xda, 0xc6, 0x86, 0x46)
            res = self.context.pVtbl.QueryInterface(self.context, &amf1contextguid, <void**> &self.context1)
            self.check(res, "AMFContext1 query")
            res = self.context1.pVtbl.InitVulkan(self.context1, NULL)
            log(f"amf_context_init() InitVulkan()={res}")
            if res != AMF_OK and res != AMF_ALREADY_INITIALIZED:
                self.check(res, "AMF Vulkan device initialization")
            self.device = <void *> self.context1.pVtbl.GetVulkanDevice(self.context1)
        log(f"amf_context_init() device=%#x", <uintptr_t> self.device)

    cdef void set_encoder_property(self, name: str, AMFVariantStruct var):
        cdef wchar_t *prop = PyUnicode_AsWideCharString(name, NULL)
        ret = self.encoder.pVtbl.SetProperty(self.encoder, prop, var)
        self.check(ret, f"AMF encoder setting property {name} to {var!r}")
        PyMem_Free(prop)

    cdef int try_encoder_property(self, name: str, AMFVariantStruct var):
        # for the tuning knobs: every one of them is a request, and which of them this
        # driver / GPU generation actually honours varies. Do not tear the encoder down
        # over one that is missing, just say so and carry on:
        cdef wchar_t *prop = PyUnicode_AsWideCharString(name, NULL)
        cdef AMF_RESULT ret = self.encoder.pVtbl.SetProperty(self.encoder, prop, var)
        PyMem_Free(prop)
        if ret:
            log("AMF encoder rejected property %r: %s", name, error_str(ret) or ret)
        return ret == 0

    cdef int set_int64_property(self, name: str, int64_t value):
        cdef AMFVariantStruct var
        if AMFVariantInit(&var):
            return 0
        AMFVariantAssignInt64(&var, value)
        return self.try_encoder_property(name, var)

    cdef int try_property(self, name: str, int64_t value):
        """ set one of the knobs from `PROPERTIES`, if this codec exposes it """
        prop = PROPERTIES.get(self.encoding, {}).get(name, "")
        if not prop:
            return 0
        return self.set_int64_property(prop, value)

    def get_encoder_property(self, name: str) -> int:
        """ read an amf_int64 property back, -1 if this encoder does not have it """
        cdef AMFVariantStruct var
        if AMFVariantInit(&var):
            return -1
        cdef wchar_t *prop = PyUnicode_AsWideCharString(name, NULL)
        cdef AMF_RESULT ret = self.encoder.pVtbl.GetProperty(self.encoder, prop, &var)
        PyMem_Free(prop)
        if ret:
            return -1
        return int(var.int64Value)

    def get_caps(self) -> Dict:
        assert self.encoder
        cdef AMFCaps *caps
        cdef AMF_RESULT r
        res = self.encoder.pVtbl.GetCaps(self.encoder, &caps)
        enc_props = ENCODING_CAPS.get(self.encoding, {})
        return get_caps(caps, enc_props)

    def amf_encoder_init(self, options: typedict) -> None:
        cdef AMFFactory *factory = get_factory()
        assert factory and self.context
        log(f"amf_encoder_init() for encoding {self.encoding!r}")

        amf_codec_name = str(AMF_ENCODINGS[self.encoding])
        cdef wchar_t *amf_codec = PyUnicode_AsWideCharString(amf_codec_name, NULL)
        cdef AMF_RESULT res = get_factory().pVtbl.CreateComponent(factory, self.context, amf_codec, &self.encoder)
        PyMem_Free(amf_codec)
        log(f"amf_encoder_init() CreateComponent()={res}")
        if res == AMF_NOT_SUPPORTED:
            message = f"{amf_codec_name!r} is not supported"
            log(message)
            raise EncodingNotSupported(message)
        self.check(res, f"AMF {self.encoding!r} encoder creation")

        self.caps = self.get_caps()
        CAPS[self.encoding] = self.caps
        log("encoder caps: %s", self.caps)

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
            # AMFVariantClear(&var)
        def setsize(prop: str) -> None:
            self.check(AMFVariantInit(&var), "AMF variant initialization")
            var.type = AMF_VARIANT_SIZE
            var.sizeValue.width = self.width
            var.sizeValue.height = self.height
            self.set_encoder_property(prop, var)
            # AMFVariantClear(&var)
        def setframerate(prop: str) -> None:
            self.check(AMFVariantInit(&var), "AMF variant initialization")
            var.type = AMF_VARIANT_RATE
            var.rateValue.num = 25
            var.rateValue.den = 1
            self.set_encoder_property(prop, var)
            # AMFVariantClear(&var)

        props = PROPERTIES.get(self.encoding)
        if not props:
            raise RuntimeError(f"unexpected encoding {self.encoding!r}")

        # `Usage` first: it is a preset which reconfigures the whole rate control
        # parameter set, so anything set before it is silently thrown away
        # (which is how the bandwidth limit used to get lost):
        usage = USAGE[self.encoding]
        if self.encoding == "h264":
            # very unreliable way of detecting older cards
            # assume that newer ones have 4GB or more
            # (older cards may report 3.9GB)
            video_memory = self.device_info.get("memory", {}).get("video", 0)
            if video_memory < 4*1024*1024*1024:
                usage = AMF_VIDEO_ENCODER_USAGE_LOW_LATENCY
        setint64(props["usage"], usage)
        setsize(props["frame-size"])
        setframerate(props["frame-rate"])

        preset = {
            "h264": get_h264_preset,
            "hevc": get_hevc_preset,
            "av1": get_av1_preset,
        }[self.encoding](quality, speed)
        setint64(props["quality-preset"], preset)

        self.set_rate_control(quality, bwlimit)

        # xpra never seeks and runs over a lossless transport, so the only keyframe we
        # need is the one that opens the stream - the same choice the x264, vpx, openh264
        # and libva encoders all make explicitly. The `Usage` preset above happens to
        # leave periodic keyframes off on current drivers, but say so rather than rely
        # on it: a 720p intra frame is more than 15x the size of an inter frame here,
        # which is a latency spike as much as it is wasted bandwidth.
        self.try_property("gop-size", 0)

        # B frames cost latency (the encoder has to hold a frame back to code the ones
        # that reference it) and are not supported by every card:
        if not options.boolget("b-frames", False):
            self.try_property("b-frames", 0)

        # let `QueryOutput` block in the driver instead of polling for it from python:
        if QUERY_TIMEOUT > 0:
            self.query_timeout = self.try_property("query-timeout", QUERY_TIMEOUT)

        # Content type. AMF only reads these at `Init` - setting them on an open encoder
        # is accepted and then ignored - but that costs us nothing: the server already
        # drops the whole video pipeline when a window changes content-type
        # (`content_type_changed` -> `reconfigure(True)` -> `cleanup_codecs`).
        screen_content = is_screen_content(self.content_types)
        if self.encoding == "h264":
            # The deblocking filter smooths away the block edges the quantizer leaves
            # behind, which is what continuous tone imagery wants; on the sharp synthetic
            # edges a desktop is made of it removes detail the encoder then has to code
            # again. Measured over 40 frames of 1280x720 with the filter turned off:
            #                            quality 35      quality 50      quality 60
            #   a window being dragged  -16.3% +0.20dB  -24.9% +1.22dB  -19.8% +1.31dB
            #   a scrolling listing      -3.7% -0.17dB   -4.1% -0.03dB   -4.3% +0.25dB
            #   video in a window       +18.8% -1.45dB   +7.3% -1.07dB   +1.9% -0.30dB
            # so it only comes off for the content-types we have positively identified
            # as screen content, and stays on for video and unclassified windows.
            # (below QP 16 the filter is a no-op anyway: the standard's alpha/beta
            # thresholds are zero there, so this changes nothing at high quality.)
            self.try_property("deblocking", not screen_content)
        elif self.encoding == "av1":
            # AV1 is the only one of the three with real screen content coding tools:
            # palette mode for the handful of colours that make up text and window
            # decorations. They cost analysis time on continuous tone imagery, where
            # there is nothing for them to find:
            self.try_property("screen-content", int(screen_content))
            self.try_property("palette-mode", int(screen_content))
            setint64("Av1Profile", AMF_VIDEO_ENCODER_AV1_PROFILE_MAIN)
            setint64("Av1Level", AMF_VIDEO_ENCODER_AV1_LEVEL_5_1)

        # init:
        res = self.encoder.pVtbl.Init(self.encoder, self.surface_format, self.width, self.height)
        self.check(res, f"AMF {self.encoding!r} encoder initialization for {self.width}x{self.height} {self.src_format}")
        log("amf_encoder_init() %s encoder initialized at %#x: %s",
            self.encoding, <uintptr_t> self.encoder, self.get_tuning_info())

    def set_rate_control(self, int quality, int bwlimit) -> None:
        # xpra drives its encoders with a quality percentage, and the video pipeline's
        # quality controller expects the encoder to follow it. Ask for a fixed quantizer
        # derived from that quality - as the x264, vpx and openh264 encoders all do -
        # rather than leaving the encoder in the bitrate driven mode `Usage` selected,
        # where the quality we were given has no effect whatsoever.
        cdef int qp
        if bwlimit > 0:
            # there is a bandwidth limit to respect, so hand the rate control back to the
            # encoder and use the quality as the ceiling it may not exceed:
            if self.try_property("rate-control", PEAK_CONSTRAINED_VBR[self.encoding]):
                self.try_property("target-bitrate", bwlimit)
                self.try_property("peak-bitrate", bwlimit)
                self.rate_control = PEAK_CONSTRAINED_VBR[self.encoding]
                return
            log("this encoder does not expose its rate control method, using constant QP")
        if not self.try_property("rate-control", CONSTANT_QP[self.encoding]):
            return
        self.rate_control = CONSTANT_QP[self.encoding]
        qp = get_qindex(quality) if self.encoding == "av1" else get_qp(quality)
        self.try_property("qp-intra", qp)
        self.try_property("qp-inter", qp)

    def get_tuning_info(self) -> Dict[str, Any]:
        """ what the encoder ended up with, which is not always what we asked for """
        props = PROPERTIES.get(self.encoding, {})
        info = {}
        for name in ("rate-control", "target-bitrate", "peak-bitrate", "qp-intra", "qp-inter",
                     "gop-size", "quality-preset", "b-frames", "deblocking"):
            prop = props.get(name, "")
            if not prop:
                continue
            value = self.get_encoder_property(prop)
            if value >= 0:
                info[name] = value
        if "rate-control" in info:
            names = RATE_CONTROL_STR.get(self.encoding, {})
            info["rate-control-name"] = names.get(info["rate-control"], "unknown")
        return info

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
            "content-types": self.content_types,
            "caps": self.caps,
        }
        if self.encoder:
            info["tuning"] = self.get_tuning_info()
        return info

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
        self.context1 = NULL
        self.frames = 0
        self.width = 0
        self.height = 0
        self.encoding = ""
        self.src_format = ""
        self.content_types = ()
        self.rate_control = -1
        self.query_timeout = 0
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
                "csc"       : {"NV12": "YUV420P"}.get(self.src_format, self.src_format),
                "frame"     : int(self.frames),
                "full-range" : False,
                #"quality"  : min(99+self.lossless, self.quality),
                #"speed"    : self.speed,
            }
        finally:
            self.frames += 1
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
        if log.is_debug_enabled():
            log(f"{memtype} surface: %s", get_surface_info(ptr))

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
        if log.is_debug_enabled():
            log("plane=%s", get_plane_info(plane))
        # texture is a `ID3D11Texture2D`:
        cdef uintptr_t texture = <uintptr_t> plane.pVtbl.GetNative(plane)
        assert texture
        return texture

    cdef bytes do_compress_image(self, uint8_t *pic_in[2], int strides[2]):
        cdef unsigned long start_time = 0    # nanoseconds!
        cdef AMFPlane *plane
        cdef uintptr_t src, dst
        cdef uintptr_t host_texture
        cdef uintptr_t gpu_texture
        cdef AMFSurface *host_surface
        cdef AMFSurface *gpu_surface
        cdef amf_int32 hpitch, vpitch
        cdef int stride
        cdef AMF_RESULT res

        if not WIN32:
            raise ImportError("amf encoder needs porting to this platform")

        from xpra.platform.win32.d3d11.device import D3D11Device
        log("D3D11Device(%#x)", <uintptr_t> self.device)
        device = D3D11Device(<uintptr_t> self.device)
        with device.get_device_context() as dc:
            if log.is_debug_enabled():
                log("device: %s", device.get_info())
                log("device context: %s", dc.get_info())

            self.alloc_surface(&host_surface, AMF_MEMORY_HOST)

            for plane_index in range(2):
                log("plane %s src data=%#x", ["Y", "UV"][plane_index], <uintptr_t> pic_in[plane_index])
                plane = host_surface.pVtbl.GetPlaneAt(host_surface, plane_index)
                assert plane
                stride = strides[plane_index]
                hpitch = plane.pVtbl.GetHPitch(plane)
                vpitch = plane.pVtbl.GetVPitch(plane)
                host_texture = <uintptr_t> plane.pVtbl.GetNative(plane)
                src = <uintptr_t> pic_in[plane_index]
                dst = <uintptr_t> host_texture
                if hpitch == stride:
                    # same stride, happy path with just one big copy:
                    memcpy(<void *> dst, <void *> src, hpitch * vpitch)
                else:
                    for y in range(vpitch):
                        memcpy(<void *> dst, <void *> src, stride)
                        dst += hpitch
                        src += stride

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
        # with a driver side timeout in place, `QueryOutput` waits for the frame itself,
        # so a couple of attempts is plenty. Without it, AMF returns `AMF_REPEAT`
        # immediately and the wait has to happen here:
        cdef int attempts = 3 if self.query_timeout else 200
        for i in range(attempts):
            res = self.encoder.pVtbl.QueryOutput(self.encoder, &data)
            log(f"QueryOutput()={res}, data=%#x", <uintptr_t> data)
            if res == 0:
                break
            if res == AMF_EOF:
                return b""
            if res == AMF_REPEAT:
                if not self.query_timeout:
                    sleep(0.001)
                continue
            self.check(res, "AMF query output")
        assert data
        if log.is_debug_enabled():
            log("data=%s", get_data_info(data))
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

    def set_encoding_speed(self, int pct) -> None:
        if self.speed==pct:
            return
        self.speed = pct
        self.do_set_encoding_speed(pct)

    cdef void do_set_encoding_speed(self, int speed):
        # nothing to do: speed selects the quality preset, which is a static property -
        # AMF only accepts it before `Init` (see `amf_encoder_init`)
        pass

    def set_encoding_quality(self, int pct) -> None:
        if self.quality==pct:
            return
        self.quality = pct
        self.do_set_encoding_quality(pct)

    cdef void do_set_encoding_quality(self, int pct):
        # the quantizer is a dynamic property, so a quality change applies from the
        # next frame - no need to re-open the encoder (which would cost a keyframe):
        if self.encoder == NULL or self.rate_control != CONSTANT_QP.get(self.encoding, -1):
            return
        props = PROPERTIES.get(self.encoding, {})
        cdef int qp = get_qindex(pct) if self.encoding == "av1" else get_qp(pct)
        for name in ("qp-intra", "qp-inter"):
            prop = props.get(name, "")
            if prop:
                self.set_int64_property(prop, qp)
        log("amf quality set to %i (qp=%i)", pct, qp)


def selftest(full=False) -> None:
    global CODECS, SAVE_TO_FILE
    from xpra.codecs.checks import testencoder
    from xpra.codecs.amf import encoder
    temp = SAVE_TO_FILE
    try:
        SAVE_TO_FILE = ""
        CODECS = testencoder(encoder, full, typedict())
        log("AMF specs()=%s", get_specs())
    finally:
        SAVE_TO_FILE = temp
