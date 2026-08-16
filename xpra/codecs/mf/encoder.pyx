# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: MediaFoundation video encoder for Windows (H.264, HEVC).
# ABOUTME: Wraps the C mf_encode API to implement xpra's VideoEncoder protocol.

#cython: wraparound=False

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec, EncodingNotSupported, get_profile, is_screen_content
from xpra.util.env import envint
from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.log import Logger
log = Logger("encoder", "mf")

from libc.stdint cimport uint8_t, uintptr_t
from libc.string cimport memset

cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "mf_encode.h":
    ctypedef struct MFEncoder:
        pass

    ctypedef enum MFEncodeStatus:
        MF_ENC_OK
        MF_ENC_NEED_MORE_INPUT
        MF_ENC_ERROR
        MF_ENC_NOT_AVAILABLE

    ctypedef struct MFEncodedFrame:
        uint8_t *data
        int      data_len
        int      is_keyframe
        int      us_input
        int      us_output

    ctypedef enum MFContentType:
        MF_CONTENT_UNKNOWN
        MF_CONTENT_SCREEN
        MF_CONTENT_VIDEO

    ctypedef enum MFEncodeProfile:
        MF_ENC_PROFILE_CONSTRAINED_BASELINE
        MF_ENC_PROFILE_MAIN
        MF_ENC_PROFILE_HIGH

    ctypedef struct MFEncoderTuning:
        int content_type
        int quality
        int speed
        int bandwidth_limit
        MFEncodeProfile profile

    ctypedef struct MFTuningInfo:
        int codec_api
        int rate_control
        int mean_bitrate
        int max_bitrate
        int quality
        int quality_vs_speed
        int gop_size
        int bframes
        int low_latency
        int content_type
        int adaptive_mode
        int cabac
        int profile

    int MF_CODEC_H264
    int MF_CODEC_HEVC

    MFEncodeStatus mf_encode_startup()
    void           mf_encode_shutdown()
    MFEncodeStatus mf_encoder_create(MFEncoder **out, int codec, int width, int height,
                                     const MFEncoderTuning *tuning)
    void           mf_encoder_destroy(MFEncoder *enc)
    MFEncodeStatus mf_encoder_set_tuning(MFEncoder *enc, const MFEncoderTuning *tuning)
    void           mf_encoder_get_tuning_info(MFEncoder *enc, MFTuningInfo *info)
    const char*    mf_rate_control_str(int rate_control)
    MFEncodeStatus mf_encoder_encode(MFEncoder *enc,
                                      const uint8_t *y_data, int y_stride,
                                      const uint8_t *u_data, int u_stride,
                                      const uint8_t *v_data, int v_stride,
                                      int width, int height,
                                      MFEncodedFrame *frame) nogil
    const char*    mf_encode_status_str(MFEncodeStatus status)
    long           mf_encoder_get_last_hr(MFEncoder *enc)
    const char*    mf_encoder_get_last_error(MFEncoder *enc)

    ctypedef void (*mf_log_fn)(const char *msg)
    void           mf_encode_set_log(mf_log_fn fn)


cdef void _mf_enc_log_callback(const char *msg) noexcept with gil:
    log("%s", msg.decode("utf-8", "replace"))


def init_module(options: dict = None) -> None:
    log("mf.encoder.init_module()")
    mf_encode_set_log(_mf_enc_log_callback)
    cdef MFEncodeStatus status = mf_encode_startup()
    if status != MF_ENC_OK:
        raise ImportError("MediaFoundation encoder startup failed: %s" %
                          mf_encode_status_str(status).decode("latin-1"))
    log("mf: encoder startup ok")


def cleanup_module() -> None:
    mf_encode_shutdown()


def get_version() -> Tuple[int, int]:
    return 1, 0


def get_type() -> str:
    return "mf"


def get_info() -> Dict[str, Any]:
    return {
        "version": get_version(),
        "type": "MediaFoundation",
        "h264-profiles": ("constrained-baseline", "main", "high"),
        "h264-default-profile": "constrained-baseline",
    }


CODECS: Dict[str, int] = {
    "h264": MF_CODEC_H264,
    "h265": MF_CODEC_HEVC,
}

H264_PROFILE_IDS = {
    "baseline": MF_ENC_PROFILE_CONSTRAINED_BASELINE,
    "constrained-baseline": MF_ENC_PROFILE_CONSTRAINED_BASELINE,
    "main": MF_ENC_PROFILE_MAIN,
    "high": MF_ENC_PROFILE_HIGH,
}


def get_h264_profile(options: typedict) -> str:
    profile = get_profile(options)
    if profile not in H264_PROFILE_IDS:
        log.warn("Warning: %r is not a valid Media Foundation H.264 profile", profile)
        log.warn(" valid profiles are: %s", ", ".join(H264_PROFILE_IDS))
        return "constrained-baseline"
    if profile == "baseline":
        return "constrained-baseline"
    return profile


def get_encodings() -> Sequence[str]:
    return tuple(CODECS.keys())


def get_min_size(encoding: str) -> Tuple[int, int]:
    return 64, 64


MAX_WIDTH, MAX_HEIGHT = 4096, 4096


# Most MFTs (the Microsoft software encoder included) only accept their tuning
# when the encoder is created, so the only way to honour a quality or speed
# change is to build a new encoder - which costs a keyframe, and on a hardware
# MFT a whole new encoding session. So we only do it for a change big enough to
# be worth that, and never more often than `XPRA_MF_RETUNE_DELAY` seconds:
RETUNE_THRESHOLD = envint("XPRA_MF_RETUNE_THRESHOLD", 30)
RETUNE_DELAY = envint("XPRA_MF_RETUNE_DELAY", 5)


# the content-types that are continuous tone rather than synthetic
# (the same split as the openh264 encoder makes):
VIDEO_CONTENT_TYPES: Sequence[str] = ("video", "picture")


def get_content_type(content_types: Sequence[str]) -> int:
    """ map xpra's window content-types onto the hints the MFT understands """
    if is_screen_content(content_types):
        return MF_CONTENT_SCREEN
    if any(x in content_types for x in VIDEO_CONTENT_TYPES):
        return MF_CONTENT_VIDEO
    # an unlabelled window is encoded as screen content, which is what it is
    # until something tells us otherwise - see `is_video_content` in `mf_encode.c`
    return MF_CONTENT_UNKNOWN


CONTENT_TYPE_NAMES: Dict[int, str] = {
    MF_CONTENT_UNKNOWN  : "unknown",
    MF_CONTENT_SCREEN   : "screen",
    MF_CONTENT_VIDEO    : "video",
}


def get_specs() -> Sequence[VideoSpec]:
    specs = []
    for encoding in CODECS:
        specs.append(VideoSpec(
            encoding=encoding,
            input_colorspace="YUV420P",
            output_colorspaces=("YUV420P", ),
            has_lossless_mode=False,
            codec_class=Encoder,
            codec_type=get_type(),
            quality=40, speed=60,
            size_efficiency=40,
            setup_cost=50,
            min_w=64, min_h=64,
            width_mask=0xFFFE, height_mask=0xFFFE,
            max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
            cpu_cost=100, gpu_cost=0,
        ))
    return tuple(specs)


cdef class Encoder:
    cdef MFEncoder *context
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object encoding
    cdef object profile
    cdef object src_format
    cdef bint full_range
    cdef int quality
    cdef int speed
    cdef int bandwidth_limit
    cdef int content_type
    cdef object content_types
    cdef double last_reinit

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height,
                     src_format: str, options: typedict) -> None:
        log("mf.encoder.init_context%s", (encoding, width, height, src_format, options))
        assert encoding in CODECS, "unsupported encoding: %s" % encoding
        assert src_format == "YUV420P", "invalid source format: %s" % src_format
        self.encoding   = encoding
        self.profile    = get_h264_profile(options) if encoding == "h264" else "main"
        self.src_format = src_format
        self.width      = width
        self.height     = height
        self.frames     = 0
        self.full_range = options.boolget("full-range", True)
        self.quality    = options.intget("quality", 50)
        self.speed      = options.intget("speed", 50)
        self.bandwidth_limit = options.intget("bandwidth-limit", 0)
        self.content_types   = options.strtupleget("content-types", ())
        self.content_type    = get_content_type(self.content_types)
        self.create_context()

    cdef void fill_tuning(self, MFEncoderTuning *tuning,
                          int quality, int speed, int bandwidth_limit) noexcept:
        memset(tuning, 0, sizeof(MFEncoderTuning))
        tuning.content_type    = self.content_type
        tuning.quality         = quality
        tuning.speed           = speed
        tuning.bandwidth_limit = bandwidth_limit
        tuning.profile         = H264_PROFILE_IDS.get(self.profile, MF_ENC_PROFILE_MAIN)

    cdef void create_context(self) except *:
        cdef MFEncoderTuning tuning
        self.fill_tuning(&tuning, self.quality, self.speed, self.bandwidth_limit)
        cdef int codec = CODECS[self.encoding]
        cdef MFEncodeStatus status = mf_encoder_create(&self.context, codec,
                                                       self.width, self.height, &tuning)
        if status != MF_ENC_OK:
            if status == MF_ENC_NOT_AVAILABLE:
                raise EncodingNotSupported("failed to create MF %s encoder (%dx%d): %s" % (
                    self.encoding, self.width, self.height,
                    mf_encode_status_str(status).decode("latin-1")))
            raise RuntimeError("failed to create MF %s encoder (%dx%d): %s" % (
                self.encoding, self.width, self.height,
                mf_encode_status_str(status).decode("latin-1")))
        self.last_reinit = monotonic()
        log("mf %s encoder created (%dx%d) content-type=%s quality=%i speed=%i",
            self.encoding, self.width, self.height,
            CONTENT_TYPE_NAMES.get(self.content_type, ""), self.quality, self.speed)

    cdef void reinit_encoder(self) except *:
        # close and reopen the MFT with the current tuning:
        # the next encoded frame will be a fresh keyframe carrying a new SPS
        cdef MFEncoder *context = self.context
        if context:
            self.context = NULL
            mf_encoder_destroy(context)
        self.create_context()

    cdef bint set_tuning(self, int quality, int speed, int bandwidth_limit) except -1:
        """ retune the running encoder, returns True if it took """
        cdef MFEncoderTuning tuning
        self.fill_tuning(&tuning, quality, speed, bandwidth_limit)
        cdef MFEncodeStatus status = mf_encoder_set_tuning(self.context, &tuning)
        log("mf set_tuning(%i, %i, %i)=%s", quality, speed, bandwidth_limit,
            mf_encode_status_str(status).decode("latin-1"))
        if status != MF_ENC_OK:
            # this MFT will not be retuned while it is running: leave our own
            # values alone so that `should_reinit` can measure the drift
            return False
        self.quality = quality
        self.speed = speed
        self.bandwidth_limit = bandwidth_limit
        return True

    cdef bint should_reinit(self, int quality, int speed) noexcept:
        if abs(quality - self.quality) < RETUNE_THRESHOLD and abs(speed - self.speed) < RETUNE_THRESHOLD:
            return False
        return monotonic() - self.last_reinit >= RETUNE_DELAY

    def get_encoding(self) -> str:
        return self.encoding

    def get_src_format(self) -> str:
        return self.src_format

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return self.context == NULL

    def get_type(self) -> str:
        return "mf"

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        log("mf encoder clean %#x", <uintptr_t> self.context)
        cdef MFEncoder *context = self.context
        if context:
            self.context = NULL
            mf_encoder_destroy(context)
        self.frames = 0
        self.width  = 0
        self.height = 0
        self.content_types = ()
        self.content_type = MF_CONTENT_UNKNOWN
        self.profile = ""

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "encoding"      : self.encoding,
            "profile"       : self.profile,
            "src_format"    : self.src_format,
            "quality"       : self.quality,
            "speed"         : self.speed,
            "content-types" : self.content_types,
            "content-type"  : CONTENT_TYPE_NAMES.get(self.content_type, ""),
        }
        if self.bandwidth_limit > 0:
            info["bandwidth-limit"] = self.bandwidth_limit
        if self.context:
            info["tuning"] = self.get_tuning_info()
        return info

    def get_tuning_info(self) -> Dict[str, Any]:
        """ what the MFT actually accepted - anything it refused is left out """
        cdef MFTuningInfo tuning
        mf_encoder_get_tuning_info(self.context, &tuning)
        info: Dict[str, Any] = {
            "codec-api" : bool(tuning.codec_api),
        }
        rate_control = mf_rate_control_str(tuning.rate_control).decode("latin-1")
        if rate_control:
            info["rate-control"] = rate_control
        for name, value in {
            "mean-bitrate"      : tuning.mean_bitrate,
            "max-bitrate"       : tuning.max_bitrate,
            "quality"           : tuning.quality,
            "quality-vs-speed"  : tuning.quality_vs_speed,
            "gop-size"          : tuning.gop_size,
            "b-frames"          : tuning.bframes,
            "low-latency"       : tuning.low_latency,
            "video-content-type": tuning.content_type,
            "adaptive-mode"     : tuning.adaptive_mode,
            "cabac"             : tuning.cabac,
            "profile"           : tuning.profile,
        }.items():
            if value >= 0:
                info[name] = value
        return info

    def compress_image(self, image: ImageWrapper, options: typedict) -> Tuple[bytes, Dict]:
        cdef MFEncodedFrame frame
        cdef MFEncodeStatus status

        assert self.context != NULL, "encoder is closed"

        cdef int width  = image.get_width()
        cdef int height = image.get_height()
        assert width  == self.width,  "width mismatch: %d vs %d"  % (width,  self.width)
        assert height == self.height, "height mismatch: %d vs %d" % (height, self.height)

        pf = image.get_pixel_format()
        if pf != "YUV420P":
            raise ValueError("expected YUV420P but got %s" % pf)

        content_types = options.strtupleget("content-types", ()) or self.content_types
        cdef int content_type = get_content_type(content_types)
        self.content_types = content_types
        cdef int quality = options.intget("quality", self.quality)
        cdef int speed = options.intget("speed", self.speed)
        cdef int bandwidth_limit = options.intget("bandwidth-limit", self.bandwidth_limit)
        if content_type != self.content_type:
            # the rate control mode, the GOP length and the encoder's own content
            # hint are all chosen when the MFT is created and no open MFT will take
            # them back, so a window that changes content-type (ie: a browser tab
            # that starts playing a video) gets a new encoder - and a new IDR:
            self.content_type = content_type
            self.quality = quality
            self.speed = speed
            self.bandwidth_limit = bandwidth_limit
            self.reinit_encoder()
        elif quality != self.quality or speed != self.speed or bandwidth_limit != self.bandwidth_limit:
            if not self.set_tuning(quality, speed, bandwidth_limit) and self.should_reinit(quality, speed):
                self.quality = quality
                self.speed = speed
                self.bandwidth_limit = bandwidth_limit
                self.reinit_encoder()

        status = self._compress_yuv420p(image, width, height, &frame)

        if status == MF_ENC_NEED_MORE_INPUT:
            return b"", {"delayed": 1}

        if status != MF_ENC_OK:
            detail  = mf_encoder_get_last_error(self.context).decode("utf-8", "replace")
            last_hr = mf_encoder_get_last_hr(self.context) & 0xFFFFFFFF
            raise RuntimeError("mf encode error: %s (detail: %s, hr=0x%08X)" % (
                mf_encode_status_str(status).decode("latin-1"), detail, last_hr))

        cdef bint full_range = image.get_full_range()
        cdef bint range_changed = full_range != self.full_range
        self.full_range = full_range
        data = bytes(frame.data[:frame.data_len])

        log("mf encoded %8d bytes %dx%d keyframe=%s (input=%dus output=%dus)",
            frame.data_len, width, height, bool(frame.is_keyframe),
            frame.us_input, frame.us_output)

        client_options: Dict[str, Any] = {
            "frame"     : int(self.frames),
        }
        if BACKWARDS_COMPATIBLE or range_changed or (self.frames == 0 and not full_range):
            client_options["full-range"] = bool(full_range)
        if frame.is_keyframe:
            client_options["type"] = "IDR"
        if self.frames == 0:
            client_options["profile"] = self.profile
        self.frames += 1
        return data, client_options

    cdef MFEncodeStatus _compress_yuv420p(self, image, int width, int height,
                                           MFEncodedFrame *frame):
        """Pin the three YUV420P planes and call the C encoder without holding the GIL."""
        cdef Py_buffer py_buf[3]
        cdef int i
        cdef const uint8_t *y_ptr
        cdef const uint8_t *u_ptr
        cdef const uint8_t *v_ptr
        cdef int y_stride, u_stride, v_stride
        cdef MFEncodeStatus status

        pixels  = image.get_pixels()
        strides = image.get_rowstride()
        assert len(pixels)  == 3, "expected 3 planes for YUV420P, got %d"  % len(pixels)
        assert len(strides) == 3, "expected 3 strides for YUV420P, got %d" % len(strides)

        y_stride = strides[0]
        u_stride = strides[1]
        v_stride = strides[2]

        for i in range(3):
            memset(&py_buf[i], 0, sizeof(Py_buffer))

        try:
            for i in range(3):
                if PyObject_GetBuffer(pixels[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                    raise ValueError("failed to read pixel plane %d from %s" % (i, type(pixels[i])))
            y_ptr = <const uint8_t *> py_buf[0].buf
            u_ptr = <const uint8_t *> py_buf[1].buf
            v_ptr = <const uint8_t *> py_buf[2].buf
            with nogil:
                status = mf_encoder_encode(self.context,
                                           y_ptr, y_stride,
                                           u_ptr, u_stride,
                                           v_ptr, v_stride,
                                           width, height, frame)
        finally:
            for i in range(3):
                if py_buf[i].buf:
                    PyBuffer_Release(&py_buf[i])
        return status


def selftest(full=False) -> None:
    log("mf encoder selftest: %s", get_info())
    from xpra.codecs.checks import testencoder
    from xpra.codecs.mf import encoder
    working = testencoder(encoder, full, typedict())
    global CODECS
    CODECS = dict((k, v) for k, v in CODECS.items() if k in working)
