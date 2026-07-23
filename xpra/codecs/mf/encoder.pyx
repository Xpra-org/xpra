# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: MediaFoundation video encoder for Windows (H.264, HEVC).
# ABOUTME: Wraps the C mf_encode API to implement xpra's VideoEncoder protocol.

#cython: wraparound=False

from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec, EncodingNotSupported
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

    int MF_CODEC_H264
    int MF_CODEC_HEVC

    MFEncodeStatus mf_encode_startup()
    void           mf_encode_shutdown()
    MFEncodeStatus mf_encoder_create(MFEncoder **out, int codec, int width, int height)
    void           mf_encoder_destroy(MFEncoder *enc)
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
    }


CODECS: Dict[str, int] = {
    "h264": MF_CODEC_H264,
    "h265": MF_CODEC_HEVC,
}


def get_encodings() -> Sequence[str]:
    return tuple(CODECS.keys())


def get_min_size(encoding: str) -> Tuple[int, int]:
    return 64, 64


MAX_WIDTH, MAX_HEIGHT = 4096, 4096


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
    cdef object src_format
    cdef bint full_range

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height,
                     src_format: str, options: typedict) -> None:
        log("mf.encoder.init_context%s", (encoding, width, height, src_format))
        assert encoding in CODECS, "unsupported encoding: %s" % encoding
        assert src_format == "YUV420P", "invalid source format: %s" % src_format
        self.encoding   = encoding
        self.src_format = src_format
        self.width      = width
        self.height     = height
        self.frames     = 0
        self.full_range = options.boolget("full-range", True)
        cdef int codec = CODECS[encoding]
        cdef MFEncodeStatus status = mf_encoder_create(&self.context, codec, width, height)
        if status != MF_ENC_OK:
            if status == MF_ENC_NOT_AVAILABLE:
                raise EncodingNotSupported("failed to create MF %s encoder (%dx%d): %s" % (
                    encoding, width, height,
                    mf_encode_status_str(status).decode("latin-1")))
            raise RuntimeError("failed to create MF %s encoder (%dx%d): %s" % (
                encoding, width, height,
                mf_encode_status_str(status).decode("latin-1")))
        log("mf %s encoder created (%dx%d)", encoding, width, height)

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

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"    : int(self.frames),
            "width"     : self.width,
            "height"    : self.height,
            "encoding"  : self.encoding,
            "src_format": self.src_format,
        }
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
