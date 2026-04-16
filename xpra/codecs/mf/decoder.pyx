# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: MediaFoundation hardware video decoder for Windows (H.264, HEVC, VP9, AV1).
# ABOUTME: Wraps the C mf_decode API to implement xpra's VideoDecoder protocol.

#cython: wraparound=False

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec
from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger
log = Logger("decoder", "mf")

from libc.stdint cimport uint8_t, uintptr_t
from xpra.buffers.membuf cimport buffer_context  # pylint: disable=syntax-error

cdef extern from "mf_decode.h":
    ctypedef struct MFDecoder:
        pass

    ctypedef enum MFDecodeStatus:
        MF_DEC_OK
        MF_DEC_NEED_MORE_INPUT
        MF_DEC_STREAM_CHANGE
        MF_DEC_ERROR
        MF_DEC_NOT_AVAILABLE

    ctypedef struct MFDecodedFrame:
        uint8_t *y_data
        uint8_t *uv_data
        int      y_stride
        int      uv_stride
        int      width
        int      height
        int      full_range
        int      us_input
        int      us_output
        int      us_extract

    int MF_CODEC_H264
    int MF_CODEC_HEVC
    int MF_CODEC_VP9
    int MF_CODEC_AV1

    MFDecodeStatus mf_decode_startup()
    void           mf_decode_shutdown()
    MFDecodeStatus mf_decoder_create(MFDecoder **out, int codec, int width, int height)
    void           mf_decoder_destroy(MFDecoder *dec)
    MFDecodeStatus mf_decoder_decode(MFDecoder *dec,
                                      const uint8_t *data, int data_len,
                                      MFDecodedFrame *frame) nogil
    MFDecodeStatus mf_decoder_flush(MFDecoder *dec, MFDecodedFrame *frame)
    void           mf_decoder_get_output_size(MFDecoder *dec, int *width, int *height)
    int            mf_decoder_is_hardware(MFDecoder *dec)
    const char*    mf_decode_status_str(MFDecodeStatus status)
    long           mf_decoder_get_last_hr(MFDecoder *dec)
    const char*    mf_decoder_get_last_error(MFDecoder *dec)

    ctypedef void (*mf_log_fn)(const char *msg)
    void           mf_decode_set_log(mf_log_fn fn)


cdef void _mf_log_callback(const char *msg) noexcept with gil:
    log("%s", msg.decode("utf-8", "replace"))


def init_module(options: dict = None) -> None:
    log("mf.init_module()")
    mf_decode_set_log(_mf_log_callback)
    cdef MFDecodeStatus status = mf_decode_startup()
    if status != MF_DEC_OK:
        raise ImportError("MediaFoundation startup failed: %s" %
                          mf_decode_status_str(status).decode("latin-1"))
    log("mf: MediaFoundation startup ok")


def cleanup_module() -> None:
    mf_decode_shutdown()


def get_version() -> Tuple[int, int]:
    return (1, 0)


def get_type() -> str:
    return "mf"


def get_info() -> Dict[str, Any]:
    return {
        "version": get_version(),
        "type": "MediaFoundation",
    }


CODECS: Dict[str, int] = {
    "h264": MF_CODEC_H264,
    "h265": MF_CODEC_HEVC,
    "vp9":  MF_CODEC_VP9,
    "av1":  MF_CODEC_AV1,
}
HARDWARE_DECODERS: list[str] = []


def get_encodings() -> Sequence[str]:
    return tuple(CODECS.keys())


def get_min_size(encoding) -> Tuple[int, int]:
    return 64, 64


MAX_WIDTH, MAX_HEIGHT = 16384, 16384


def get_specs() -> Sequence[VideoSpec]:
    specs = []
    for encoding in CODECS:
        hardware = encoding in HARDWARE_DECODERS
        specs.append(VideoSpec(
            encoding=encoding,
            input_colorspace="YUV420P",
            output_colorspaces=("NV12", ),
            has_lossless_mode=False,
            codec_class=Decoder,
            codec_type=get_type(),
            quality=40, speed=50 + 50 * int(hardware),
            size_efficiency=40 + 40 * int(hardware),
            setup_cost=int(hardware) * 50,
            min_w=64, min_h=64,  # D3D11 device creation is ~10ms; not worth it for small images
            width_mask=0xFFFE, height_mask=0xFFFE,
            max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
            cpu_cost=int(not hardware) * 100, gpu_cost=int(hardware) * 100,
        ))
    return tuple(specs)


cdef class Decoder:
    cdef MFDecoder *context
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object colorspace
    cdef object encoding

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("mf.init_context%s", (encoding, width, height, colorspace))
        assert encoding in CODECS, "unsupported encoding: %s" % encoding
        assert colorspace == "YUV420P", "invalid colorspace: %s" % colorspace
        self.encoding = encoding
        self.colorspace = colorspace
        self.width = width
        self.height = height
        self.frames = 0
        cdef int codec = CODECS[encoding]
        cdef MFDecodeStatus status = mf_decoder_create(&self.context, codec, width, height)
        if status != MF_DEC_OK:
            raise RuntimeError("failed to create MF %s decoder (%dx%d): %s" % (
                encoding, width, height, mf_decode_status_str(status).decode("latin-1")))
        hardware = bool(mf_decoder_is_hardware(self.context))
        log("mf %s decoder created: hardware=%s", encoding, hardware)
        if hardware:
            HARDWARE_DECODERS.append(encoding)

    def get_encoding(self) -> str:
        return self.encoding

    def get_colorspace(self) -> str:
        return self.colorspace

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
        log("mf close context %#x", <uintptr_t> self.context)
        cdef MFDecoder *context = self.context
        if context:
            self.context = NULL
            mf_decoder_destroy(context)
        self.frames = 0
        self.width = 0
        self.height = 0
        self.colorspace = ""
        self.encoding = ""

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"    : int(self.frames),
            "width"     : self.width,
            "height"    : self.height,
            "colorspace": self.colorspace,
            "encoding"  : self.encoding,
        }
        if self.context:
            info["hardware"] = bool(mf_decoder_is_hardware(self.context))
        return info

    def decompress_image(self, data: bytes, options: typedict) -> ImageWrapper:
        cdef MFDecodedFrame frame
        cdef MFDecodeStatus status
        cdef const uint8_t *src
        cdef int src_len
        cdef int new_w, new_h

        assert self.context != NULL, "decoder is closed"

        start = monotonic()
        with buffer_context(data) as bc:
            src = <const uint8_t *> (<uintptr_t> int(bc))
            src_len = len(bc)
            with nogil:
                status = mf_decoder_decode(self.context, src, src_len, &frame)

        if status == MF_DEC_NEED_MORE_INPUT:
            log("mf: need more input (buffering)")
            return None

        if status == MF_DEC_STREAM_CHANGE:
            # C layer handles renegotiation and retries ProcessOutput,
            # but if the frame after renegotiation still needs more input:
            log("mf: stream change, updating dimensions")
            mf_decoder_get_output_size(self.context, &new_w, &new_h)
            self.width = new_w
            self.height = new_h
            return None

        if status != MF_DEC_OK:
            detail = mf_decoder_get_last_error(self.context).decode("utf-8", "replace")
            last_hr = mf_decoder_get_last_hr(self.context) & 0xFFFFFFFF
            raise RuntimeError("mf decode error: %s (detail: %s, hr=0x%08X)" % (
                mf_decode_status_str(status).decode("latin-1"), detail, last_hr))

        # Output NV12 directly — the GL backing handles NV12 via shader or CSC fallback
        cdef int y_size = frame.y_stride * frame.height
        cdef int uv_size = frame.uv_stride * (frame.height // 2)
        copy_start = monotonic()
        y_plane = frame.y_data[:y_size]
        uv_plane = frame.uv_data[:uv_size]
        copy_end = monotonic()
        pixels = (y_plane, uv_plane)
        strides = (frame.y_stride, frame.uv_stride)

        self.frames += 1
        cdef int us_copy = int((copy_end - copy_start) * 1000000)
        cdef int us_total = int((copy_end - start) * 1000000)
        log("mf decoded %8d bytes %dx%d in %dms: input=%dus output=%dus extract=%dus copy=%dus (%.1fMB)",
            src_len, frame.width, frame.height, (us_total + 500) // 1000,
            frame.us_input, frame.us_output, frame.us_extract, us_copy,
            (y_size + uv_size) / 1048576.0)

        full_range = options.boolget("full-range")
        return ImageWrapper(0, 0, self.width, self.height,
                            pixels, "NV12", 24, strides, 2,
                            ImageWrapper.PLANAR_2,
                            full_range=full_range)


def selftest(full=False) -> None:
    log("mf selftest: %s", get_info())
    from xpra.codecs.checks import testdecoder
    from xpra.codecs.mf import decoder
    working = testdecoder(decoder, full)
    global CODECS
    CODECS = dict((k, v) for k, v in CODECS.items() if k in working)
