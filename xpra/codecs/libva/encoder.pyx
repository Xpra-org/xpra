# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: libva hardware encoder.
# ABOUTME: Wraps the C va_encode API; accepts NV12 system-memory frames.
# accepts NV12 system-memory frames only
# emits periodic key frames and P frames
# copies into VA surfaces; direct dmabuf/VA surface import is future work
# future work: more encodings/profiles, async queues, set_speed, set_quality

#cython: wraparound=False

import os
from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec, EncodingNotSupported
from xpra.codecs.vacommon import config_libva_logging
from xpra.codecs.image import ImageWrapper
from xpra.util.objects import typedict, AtomicInteger
from xpra.log import Logger

log = Logger("encoder", "libva")

from libc.stdint cimport uint8_t, uintptr_t
from libc.string cimport memset


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS


cdef void libva_log_callback(const char *msg) noexcept with gil:
    log("%s", msg.decode("utf-8", "replace"))


cdef extern from "va_encode.h":
    ctypedef struct LibVAEncoder:
        pass

    ctypedef enum LibVAEncodeStatus:
        LIBVA_ENC_OK
        LIBVA_ENC_ERROR
        LIBVA_ENC_NOT_AVAILABLE

    ctypedef enum LibVAEncodeFrameType:
        LIBVA_ENC_FRAME_UNKNOWN
        LIBVA_ENC_FRAME_IDR
        LIBVA_ENC_FRAME_I
        LIBVA_ENC_FRAME_P

    ctypedef struct LibVAEncodedFrame:
        uint8_t *data
        int      size
        LibVAEncodeFrameType frame_type
        int      us_copy
        int      us_submit
        int      us_sync

    ctypedef void (*libva_log_fn)(const char *msg)

    void              libva_encode_set_log(libva_log_fn fn)
    LibVAEncodeStatus libva_encode_startup()
    void              libva_encode_shutdown()
    const char       *libva_encode_get_device()
    const char       *libva_encode_get_vendor()
    const char       *libva_encode_get_last_error()
    int               libva_encode_get_major()
    int               libva_encode_get_minor()

    LibVAEncodeStatus libva_encoder_create(LibVAEncoder **out, const char *encoding,
                                           int width, int height,
                                           int quality, int speed) nogil
    void              libva_encoder_destroy(LibVAEncoder *enc) nogil
    LibVAEncodeStatus libva_encoder_encode(LibVAEncoder *enc,
                                           const uint8_t *y, int y_stride,
                                           const uint8_t *uv, int uv_stride,
                                           LibVAEncodedFrame *frame) nogil

    int               libva_encoder_get_width(LibVAEncoder *enc)
    int               libva_encoder_get_height(LibVAEncoder *enc)
    int               libva_encoder_get_last_status(LibVAEncoder *enc)
    const char       *libva_encoder_get_last_error(LibVAEncoder *enc)
    const char       *libva_encode_status_str(LibVAEncodeStatus status)


cdef str frame_type_name(LibVAEncodeFrameType frame_type):
    if frame_type == LIBVA_ENC_FRAME_IDR:
        return "IDR"
    if frame_type == LIBVA_ENC_FRAME_I:
        return "I"
    if frame_type == LIBVA_ENC_FRAME_P:
        return "P"
    return ""


generation = AtomicInteger()

ENCODINGS: list[str] = ["h264", "vp8", "vp9"]


def init_module(options: dict = None) -> None:
    log("libva.encoder.init_module()")
    config_libva_logging()
    libva_encode_set_log(libva_log_callback)
    cdef LibVAEncodeStatus status = libva_encode_startup()
    if status != LIBVA_ENC_OK:
        detail = libva_encode_get_last_error().decode("utf-8", "replace")
        msg = "libva encoder startup failed: %s" % libva_encode_status_str(status).decode("latin-1")
        if detail:
            msg += " (%s)" % detail
        raise ImportError(msg)


def cleanup_module() -> None:
    libva_encode_shutdown()


def get_version() -> Tuple[int, int]:
    return (1, 0)


def get_type() -> str:
    return "libva"


def get_info() -> Dict[str, Any]:
    return {
        "version": get_version(),
        "type": "libva",
        "formats": ("NV12", ),
        "device": libva_encode_get_device().decode("utf-8", "replace"),
        "vendor": libva_encode_get_vendor().decode("utf-8", "replace"),
        "libva": (libva_encode_get_major(), libva_encode_get_minor()),
    }


def get_encodings() -> Sequence[str]:
    return tuple(ENCODINGS)


MAX_WIDTH, MAX_HEIGHT = 4096, 4096


def get_specs() -> Sequence[VideoSpec]:
    return tuple(
        VideoSpec(
            encoding=encoding,
            input_colorspace="NV12",
            output_colorspaces=("YUV420P", ),
            has_lossless_mode=False,
            codec_class=Encoder, codec_type=get_type(),
            quality=75, speed=75,
            size_efficiency=40,
            setup_cost=15,
            min_w=64, min_h=64,
            width_mask=0xFFFE, height_mask=0xFFFE,
            max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
            cpu_cost=35,
            gpu_cost=50,
        )
        for encoding in ENCODINGS
    )


cdef class Encoder:
    cdef LibVAEncoder *context
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef int quality
    cdef int speed
    cdef object src_format
    cdef object encoding
    cdef object file
    cdef uint8_t ready

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, src_format: str,
                     options: typedict) -> None:
        log("libva.encoder.init_context%s", (encoding, width, height, src_format, options))
        assert encoding in ENCODINGS, "unsupported encoding: %s" % encoding
        assert src_format == "NV12", "invalid source format: %s" % src_format
        assert options.intget("scaled-width", width) == width, "libva encoder does not handle scaling"
        assert options.intget("scaled-height", height) == height, "libva encoder does not handle scaling"
        if width & 1 or height & 1:
            raise ValueError("invalid odd width %i or height %i for NV12" % (width, height))

        self.encoding = encoding
        self.src_format = src_format
        self.width = width
        self.height = height
        self.quality = options.intget("quality", 50)
        self.speed = options.intget("speed", 50)
        self.frames = 0

        cdef bytes encoding_bytes = encoding.encode("latin-1")
        cdef const char *encoding_name = encoding_bytes
        cdef LibVAEncodeStatus status
        with nogil:
            status = libva_encoder_create(&self.context, encoding_name,
                                          width, height, self.quality, self.speed)
        if status != LIBVA_ENC_OK:
            status_str = libva_encode_status_str(status).decode("latin-1")
            detail = libva_encode_get_last_error().decode("utf-8", "replace")
            msg = "failed to create libva %s encoder (%dx%d): %s" % (
                encoding, width, height, status_str)
            if detail:
                msg += " (%s)" % detail
            if status == LIBVA_ENC_NOT_AVAILABLE:
                raise EncodingNotSupported(msg)
            raise RuntimeError(msg)

        self.file = None
        save_to_file = os.environ.get("XPRA_SAVE_TO_FILE", "")
        if save_to_file:
            filename = save_to_file + "libva-" + str(generation.increase()) + "." + encoding
            self.file = open(filename, "wb")
            log.info("saving %s stream to %r", encoding, filename)

        self.ready = 1
        log("libva %s encoder initialized", encoding)

    def is_ready(self) -> bool:
        return bool(self.ready)

    def is_closed(self) -> bool:
        return self.context == NULL

    def get_encoding(self) -> str:
        return self.encoding

    def get_type(self) -> str:
        return "libva"

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_src_format(self) -> str:
        return self.src_format

    # Follow-up work intentionally deferred from the first incarnation:
    # - H.265/AV1 and additional VP9 profile probing / VideoSpec entries.
    # - RGB/YUV420P upload paths, or a direct dependency on libyuv CSC.
    # - dmabuf / VA surface import to avoid CPU staging copies.
    # - persistent VA buffers and async surface queues.
    # - set_encoding_quality() via CQP QP updates or encoder reconfigure.
    # - set_encoding_speed() via VA quality-level or driver-specific controls.
    # - bitrate/rate-control modes and better multi-GPU device scoring.

    def __repr__(self):
        if not self.ready:
            return "libva_encoder(uninitialized)"
        return "libva_encoder(%ix%i)" % (self.width, self.height)

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        cdef LibVAEncoder *context = self.context
        if context != NULL:
            log("libva encoder close context %#x", <uintptr_t> context)
            self.context = NULL
            with nogil:
                libva_encoder_destroy(context)
        self.ready = 0
        self.frames = 0
        self.width = 0
        self.height = 0
        self.src_format = ""
        self.encoding = ""
        f = self.file
        if f:
            self.file = None
            f.close()

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames": int(self.frames),
            "width": self.width,
            "height": self.height,
            "src_format": self.src_format,
            "encoding": self.encoding,
            "quality": self.quality,
            "speed": self.speed,
        }
        return info

    def compress_image(self, image: ImageWrapper, options: typedict) -> Tuple[bytes, Dict]:
        cdef LibVAEncodedFrame frame
        cdef Py_buffer y_buf
        cdef Py_buffer uv_buf
        cdef LibVAEncodeStatus status = LIBVA_ENC_ERROR

        assert self.context != NULL, "encoder is closed"
        assert image.get_width() >= self.width
        assert image.get_height() >= self.height
        if image.get_pixel_format() != "NV12":
            raise ValueError("expected NV12 but got %s" % image.get_pixel_format())

        pixels = image.get_pixels()
        strides = image.get_rowstride()
        assert len(pixels) == 2, "NV12 image pixels does not have 2 planes"
        assert len(strides) == 2, "NV12 image rowstride does not have 2 values"
        cdef int y_stride = strides[0]
        cdef int uv_stride = strides[1]

        start = monotonic()
        memset(&y_buf, 0, sizeof(Py_buffer))
        memset(&uv_buf, 0, sizeof(Py_buffer))
        try:
            if PyObject_GetBuffer(pixels[0], &y_buf, PyBUF_ANY_CONTIGUOUS):
                raise ValueError("failed to read NV12 Y plane from %s" % type(pixels[0]))
            if PyObject_GetBuffer(pixels[1], &uv_buf, PyBUF_ANY_CONTIGUOUS):
                raise ValueError("failed to read NV12 UV plane from %s" % type(pixels[1]))
            with nogil:
                status = libva_encoder_encode(self.context,
                                              <const uint8_t *> y_buf.buf, y_stride,
                                              <const uint8_t *> uv_buf.buf, uv_stride,
                                              &frame)
        finally:
            if uv_buf.buf:
                PyBuffer_Release(&uv_buf)
            if y_buf.buf:
                PyBuffer_Release(&y_buf)

        if status != LIBVA_ENC_OK:
            detail = libva_encoder_get_last_error(self.context).decode("utf-8", "replace")
            last_sts = libva_encoder_get_last_status(self.context)
            raise RuntimeError("libva encode error: %s (detail: %s, sts=%d)" % (
                libva_encode_status_str(status).decode("latin-1"), detail, last_sts))

        bdata = frame.data[:frame.size]
        f = self.file
        if f:
            f.write(bdata)
        client_options = {
            "frame": int(self.frames),
            "full-range": image.get_full_range(),
        }
        frame_type = frame_type_name(frame.frame_type)
        if frame_type:
            client_options["type"] = frame_type
        self.frames += 1
        elapsed = int((monotonic() - start) * 1000000)
        log("libva encoded %dx%d frame %i as %s: %i bytes in %dms copy=%dus submit=%dus sync=%dus",
            self.width, self.height, self.frames, client_options.get("type", ""),
            len(bdata), (elapsed + 500) // 1000,
            frame.us_copy, frame.us_submit, frame.us_sync)
        return bdata, client_options

    def flush(self, delayed: int = 0) -> Tuple[bytes, Dict]:
        return b"", {}


def selftest(full=False) -> None:
    log("libva encoder selftest: %s", get_info())
    from xpra.codecs.checks import testencoder
    from xpra.codecs.libva import encoder
    ENCODINGS[:] = testencoder(encoder, full, typedict())
    assert ENCODINGS
