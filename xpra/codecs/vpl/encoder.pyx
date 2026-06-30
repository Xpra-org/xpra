# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: Intel oneVPL H.264 hardware encoder.
# ABOUTME: Wraps the C vpl_encode API; accepts NV12 system-memory frames.

#cython: wraparound=False

import os
from threading import RLock
from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec, get_profile
from xpra.codecs.image import ImageWrapper
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict, AtomicInteger
from xpra.log import Logger

log = Logger("encoder", "vpl")

from libc.stdint cimport uint8_t, uintptr_t
from libc.string cimport memset
from xpra.codecs.vpl.common cimport vpl_log_fn, vpl_log_callback


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS


cdef extern from "vpl_encode.h":
    ctypedef struct VPLEncoder:
        pass

    ctypedef enum VPLEncodeStatus:
        VPL_ENC_OK
        VPL_ENC_NEED_MORE_INPUT
        VPL_ENC_ERROR
        VPL_ENC_NOT_AVAILABLE

    ctypedef enum VPLEncodeFrameType:
        VPL_ENC_FRAME_UNKNOWN
        VPL_ENC_FRAME_IDR
        VPL_ENC_FRAME_I
        VPL_ENC_FRAME_P

    ctypedef enum VPLEncodeProfile:
        VPL_ENC_PROFILE_CONSTRAINED_BASELINE
        VPL_ENC_PROFILE_MAIN
        VPL_ENC_PROFILE_HIGH

    ctypedef struct VPLEncodedFrame:
        uint8_t *data
        int      size
        VPLEncodeFrameType frame_type
        int      us_copy
        int      us_submit
        int      us_sync

    VPLEncodeStatus vpl_encode_startup()
    void            vpl_encode_shutdown()
    VPLEncodeStatus vpl_encoder_create(VPLEncoder **out, int width, int height,
                                        int quality, int speed, VPLEncodeProfile profile,
                                        int low_power) nogil
    void            vpl_encoder_destroy(VPLEncoder *enc) nogil
    VPLEncodeStatus vpl_encoder_encode(VPLEncoder *enc,
                                        const uint8_t *y, int y_stride,
                                        const uint8_t *uv, int uv_stride,
                                        VPLEncodedFrame *frame) nogil
    VPLEncodeStatus vpl_encoder_flush(VPLEncoder *enc, VPLEncodedFrame *frame) nogil
    VPLEncodeStatus vpl_encoder_set_quality(VPLEncoder *enc, int quality)
    int             vpl_encoder_is_hardware(VPLEncoder *enc)
    int             vpl_encoder_get_width(VPLEncoder *enc)
    int             vpl_encoder_get_height(VPLEncoder *enc)
    int             vpl_encoder_get_last_status(VPLEncoder *enc)
    const char*     vpl_encoder_get_last_error(VPLEncoder *enc)
    const char*     vpl_encode_status_str(VPLEncodeStatus status)

    void            vpl_encode_set_log(vpl_log_fn fn)


cdef str frame_type_name(VPLEncodeFrameType frame_type):
    if frame_type == VPL_ENC_FRAME_IDR:
        return "IDR"
    if frame_type == VPL_ENC_FRAME_I:
        return "I"
    if frame_type == VPL_ENC_FRAME_P:
        return "P"
    return ""


generation = AtomicInteger()
PROFILE_IDS = {
    "baseline": VPL_ENC_PROFILE_CONSTRAINED_BASELINE,
    "constrained-baseline": VPL_ENC_PROFILE_CONSTRAINED_BASELINE,
    "main": VPL_ENC_PROFILE_MAIN,
    "high": VPL_ENC_PROFILE_HIGH,
}


def get_vpl_profile(options: typedict) -> str:
    profile = get_profile(options, default_profile="main")
    if profile not in PROFILE_IDS:
        log.warn("Warning: %r is not a valid VPL H.264 profile", profile)
        log.warn(" valid profiles are: %s", ", ".join(PROFILE_IDS))
        return "main"
    if profile == "baseline":
        return "constrained-baseline"
    return profile


def init_module(options: dict = None) -> None:
    log("vpl.encoder.init_module()")
    vpl_encode_set_log(vpl_log_callback)
    cdef VPLEncodeStatus status = vpl_encode_startup()
    if status != VPL_ENC_OK:
        raise ImportError("oneVPL H.264 encoder startup failed: %s" %
                          vpl_encode_status_str(status).decode("latin-1"))


def cleanup_module() -> None:
    vpl_encode_shutdown()


def get_version() -> Tuple[int, int]:
    return 1, 0


def get_type() -> str:
    return "vpl"


def get_info() -> Dict[str, Any]:
    return {
        "version": get_version(),
        "type": "vpl",
        "formats": ("NV12", ),
        "profiles": ("constrained-baseline", "main", "high"),
        "default-profile": "main",
        "default-low-power": False,
    }


def get_encodings() -> Sequence[str]:
    return ("h264", )


MAX_WIDTH, MAX_HEIGHT = 4096, 4096


def get_specs() -> Sequence[VideoSpec]:
    return (
        VideoSpec(
            encoding="h264",
            input_colorspace="NV12",
            output_colorspaces=("YUV420P", ),
            has_lossless_mode=False,
            codec_class=Encoder,
            codec_type=get_type(),
            quality=80, speed=90,
            size_efficiency=70,
            setup_cost=10,
            min_w=64, min_h=64,
            width_mask=0xFFFE, height_mask=0xFFFE,
            max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
            cpu_cost=10,
            gpu_cost=50,
        ),
    )


cdef class Encoder:
    cdef VPLEncoder *context
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef int quality
    cdef int speed
    cdef int low_power
    cdef object profile
    cdef object src_format
    cdef object encoding
    cdef object file
    cdef object lock
    cdef uint8_t ready
    cdef int delayed
    cdef int full_range

    cdef object __weakref__

    def __cinit__(self):
        self.lock = RLock()

    def init_context(self, encoding: str, int width, int height, src_format: str,
                     options: typedict) -> None:
        log("vpl.encoder.init_context%s", (encoding, width, height, src_format, options))
        assert encoding == "h264", "unsupported encoding: %s" % encoding
        assert src_format == "NV12", "invalid source format: %s" % src_format
        assert options.intget("scaled-width", width) == width, "vpl encoder does not handle scaling"
        assert options.intget("scaled-height", height) == height, "vpl encoder does not handle scaling"
        if width & 1 or height & 1:
            raise ValueError("invalid odd width %i or height %i for NV12" % (width, height))

        self.encoding = encoding
        self.src_format = src_format
        self.width = width
        self.height = height
        self.quality = options.intget("quality", 50)
        self.speed = options.intget("speed", 50)
        self.profile = get_vpl_profile(options)
        self.low_power = options.boolget("h264.low-power", False)
        self.frames = 0
        self.delayed = 0
        self.full_range = options.boolget("full-range", True)

        cdef VPLEncodeStatus status
        cdef VPLEncodeProfile profile_id = PROFILE_IDS[self.profile]
        with nogil:
            status = vpl_encoder_create(&self.context, width, height, self.quality,
                                        self.speed, profile_id, self.low_power)
        if status != VPL_ENC_OK:
            raise RuntimeError("failed to create VPL encoder (%dx%d): %s" % (
                width, height, vpl_encode_status_str(status).decode("latin-1")))

        self.file = None
        save_to_file = os.environ.get("XPRA_SAVE_TO_FILE", "")
        if save_to_file:
            filename = save_to_file + "vpl-" + str(generation.increase()) + ".h264"
            self.file = open(filename, "wb")
            log.info("saving h264 stream to %r", filename)

        self.ready = 1
        log("vpl h264 %s profile encoder initialized: hardware=%s, low-power=%s",
            self.profile, bool(vpl_encoder_is_hardware(self.context)), bool(self.low_power))

    def is_ready(self) -> bool:
        return bool(self.ready)

    def is_closed(self) -> bool:
        return self.context == NULL

    def get_encoding(self) -> str:
        return self.encoding

    def get_type(self) -> str:
        return "vpl"

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_src_format(self) -> str:
        return self.src_format

    # ── why there is no set_encoding_speed() ───────────────────────────
    # xpra's "speed" maps to MFX mfx.TargetUsage (1..7), which is *not*
    # a per-frame knob — it's a preset selected at Init that picks an
    # entire encoding pipeline. Changing it at runtime touches:
    #
    #  - VME (motion estimation) hardware: search pattern, range, sub-pel
    #    refinement — programmed into GPU register state and LUTs at Init.
    #  - RDO depth: TU=1 walks every CU/PU partition, TU=7 uses early
    #    termination. Scratch buffers are sized for the chosen depth.
    #  - Reference topology (NumRefFrame, GopRefDist). A change invalidates
    #    the DPB and any in-flight async frames, and forces new SPS/PPS —
    #    so an IDR is unavoidable for the decoder to pick up the headers.
    #  - BRC internal state, which gets reseeded.
    #  - The command-buffer template the driver "compiles" at Init.
    #
    # In practice this means MFXVideoENCODE_Reset (when accepted) does the
    # same teardown/rebuild as Close+Init, and many drivers just refuse
    # with MFX_ERR_INCOMPATIBLE_VIDEO_PARAM. By contrast QP is a single
    # integer fed to the quantizer per macroblock — no search/partition/
    # ref/buffer state depends on it, which is why per-frame
    # mfxEncodeCtrl.QP works with no IDR and no driver round-trip.
    #
    # A future set_encoding_speed() should therefore:
    #   1. Batch — don't honour every small delta.
    #   2. Coincide with an IDR you'd send anyway (keyframe interval,
    #      scene change, explicit client request).
    #   3. Fall back to destroy+create when Reset is refused — at that
    #      point the cost is dominated by the pipeline rebuild, not by
    #      which API was used.
    def set_encoding_quality(self, int pct) -> None:
        # Per-frame mfxEncodeCtrl.QP override. Only effective in CQP mode;
        # ICQ-driven sessions fall through silently (set_quality returns
        # VPL_ENC_NOT_AVAILABLE) — speed/quality reconfig for ICQ needs
        # the heavier MFXVideoENCODE_Reset path that pass 2 will add.
        if pct < 0 or pct > 100:
            raise ValueError("invalid quality percentage: %s" % pct)
        with self.lock:
            if self.context == NULL:
                return
            if pct == self.quality:
                return
            # Mirror x264: ignore sub-5pt jitter, but always honour transitions
            # to/from the boundary so a user-pinned high or low quality lands.
            if abs(self.quality - pct) <= 4 and pct not in (0, 100) and self.quality not in (0, 100):
                return
            self.quality = pct
            vpl_encoder_set_quality(self.context, pct)

    def __repr__(self):
        if not self.ready:
            return "vpl_encoder(uninitialized)"
        return "vpl_encoder(%ix%i)" % (self.width, self.height)

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        cdef VPLEncoder *context
        with self.lock:
            context = self.context
            if context != NULL:
                log("vpl encoder close context %#x", <uintptr_t> context)
                self.context = NULL
                with nogil:
                    vpl_encoder_destroy(context)
            self.ready = 0
            self.frames = 0
            self.width = 0
            self.height = 0
            self.src_format = ""
            self.encoding = ""
            self.delayed = 0
            f = self.file
            if f:
                self.file = None
                f.close()

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"    : int(self.frames),
            "width"     : self.width,
            "height"    : self.height,
            "src_format": self.src_format,
            "encoding"  : self.encoding,
            "quality"   : self.quality,
            "speed"     : self.speed,
            "profile"   : self.profile,
            "low-power" : bool(self.low_power),
            "delayed"   : self.delayed,
        }
        if self.context:
            info["hardware"] = bool(vpl_encoder_is_hardware(self.context))
        return info

    cdef tuple _make_result(self, VPLEncodedFrame *frame, full_range=False):
        bdata = frame.data[:frame.size]
        f = self.file
        if f:
            f.write(bdata)
        client_options = {
            "frame": int(self.frames),
        }
        frame_type = frame_type_name(frame.frame_type)
        if frame_type:
            client_options["type"] = frame_type
        if self.delayed:
            self.delayed = max(0, self.delayed - 1)
            client_options["delayed"] = self.delayed
        if BACKWARDS_COMPATIBLE or self.full_range != full_range or (self.frames == 0 and not full_range):
            client_options["full-range"] = full_range
        if self.frames == 0:
            client_options["profile"] = self.profile
        self.frames += 1
        return bdata, client_options

    def compress_image(self, image: ImageWrapper, options: typedict) -> Tuple[bytes, Dict]:
        cdef VPLEncodedFrame frame
        cdef Py_buffer y_buf
        cdef Py_buffer uv_buf
        cdef VPLEncodeStatus status = VPL_ENC_ERROR
        cdef int requested_quality
        cdef int y_stride
        cdef int uv_stride

        with self.lock:
            assert self.context != NULL, "encoder is closed"
            assert image.get_width() >= self.width
            assert image.get_height() >= self.height
            if image.get_pixel_format() != "NV12":
                raise ValueError("expected NV12 but got %s" % image.get_pixel_format())

            requested_quality = options.intget("quality", -1)
            if requested_quality >= 0:
                self.set_encoding_quality(requested_quality)

            pixels = image.get_pixels()
            strides = image.get_rowstride()
            assert len(pixels) == 2, "NV12 image pixels does not have 2 planes"
            assert len(strides) == 2, "NV12 image rowstride does not have 2 values"
            y_stride = strides[0]
            uv_stride = strides[1]

            start = monotonic()
            memset(&y_buf, 0, sizeof(Py_buffer))
            memset(&uv_buf, 0, sizeof(Py_buffer))
            try:
                if PyObject_GetBuffer(pixels[0], &y_buf, PyBUF_ANY_CONTIGUOUS):
                    raise ValueError("failed to read NV12 Y plane from %s" % type(pixels[0]))
                if PyObject_GetBuffer(pixels[1], &uv_buf, PyBUF_ANY_CONTIGUOUS):
                    raise ValueError("failed to read NV12 UV plane from %s" % type(pixels[1]))
                with nogil:
                    status = vpl_encoder_encode(self.context,
                                                <const uint8_t *> y_buf.buf, y_stride,
                                                <const uint8_t *> uv_buf.buf, uv_stride,
                                                &frame)
            finally:
                if uv_buf.buf:
                    PyBuffer_Release(&uv_buf)
                if y_buf.buf:
                    PyBuffer_Release(&y_buf)

            if status == VPL_ENC_NEED_MORE_INPUT:
                self.delayed += 1
                return b"", {"frame": int(self.frames), "delayed": self.delayed}

            if status != VPL_ENC_OK:
                detail = vpl_encoder_get_last_error(self.context).decode("utf-8", "replace")
                last_sts = vpl_encoder_get_last_status(self.context)
                raise RuntimeError("vpl encode error: %s (detail: %s, sts=%d)" % (
                    vpl_encode_status_str(status).decode("latin-1"), detail, last_sts))

            bdata, client_options = self._make_result(&frame, image.get_full_range())
            elapsed = int((monotonic() - start) * 1000000)
            log("vpl encoded %dx%d frame %i as %s: %i bytes in %dms copy=%dus submit=%dus sync=%dus",
                self.width, self.height, self.frames, client_options.get("type", ""),
                len(bdata), (elapsed + 500) // 1000,
                frame.us_copy, frame.us_submit, frame.us_sync)
            return bdata, client_options

    def flush(self, delayed: int = 0) -> Tuple[bytes, Dict]:
        cdef VPLEncodedFrame frame
        cdef VPLEncodeStatus status
        with self.lock:
            if self.context == NULL:
                return b"", {}
            with nogil:
                status = vpl_encoder_flush(self.context, &frame)
            if status == VPL_ENC_NEED_MORE_INPUT:
                self.delayed = 0
                return b"", {"delayed": 0}
            if status != VPL_ENC_OK:
                detail = vpl_encoder_get_last_error(self.context).decode("utf-8", "replace")
                last_sts = vpl_encoder_get_last_status(self.context)
                raise RuntimeError("vpl flush error: %s (detail: %s, sts=%d)" % (
                    vpl_encode_status_str(status).decode("latin-1"), detail, last_sts))
            return self._make_result(&frame, self.full_range)


def selftest(full=False) -> None:
    log("vpl encoder selftest: %s", get_info())
    from xpra.codecs.checks import testencoder
    from xpra.codecs.vpl import encoder
    assert testencoder(encoder, full, typedict())
