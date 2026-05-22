# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: Intel oneVPL HEVC 4:4:4 hardware decoder for Windows.
# ABOUTME: Wraps the C vpl_decode API; outputs AYUV for the GL shader pipeline.

#cython: wraparound=False

import os
from threading import Lock
from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec
from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger
log = Logger("decoder", "vpl")

VPL_ENABLED = os.environ.get("XPRA_VPL", "1") != "0"

from libc.stdint cimport uint8_t, uintptr_t
from xpra.buffers.membuf cimport buffer_context  # pylint: disable=syntax-error


cdef extern from "vpl_decode.h":
    ctypedef struct VPLDecoder:
        pass

    ctypedef enum VPLDecodeStatus:
        VPL_DEC_OK
        VPL_DEC_NEED_MORE_INPUT
        VPL_DEC_STREAM_CHANGE
        VPL_DEC_ERROR
        VPL_DEC_NOT_AVAILABLE

    ctypedef enum VPLPixelFormat:
        VPL_FMT_UNKNOWN
        VPL_FMT_AYUV
        VPL_FMT_Y410

    ctypedef struct VPLDecodedFrame:
        uint8_t *data
        int      stride
        int      width
        int      height
        int      full_range
        VPLPixelFormat format
        int      us_submit
        int      us_sync
        int      us_map

    VPLDecodeStatus vpl_decode_startup()
    void            vpl_decode_shutdown()
    VPLDecodeStatus vpl_decoder_create(VPLDecoder **out, int width, int height,
                                        int chroma444, int bit_depth) nogil
    void            vpl_decoder_destroy(VPLDecoder *dec) nogil
    VPLDecodeStatus vpl_decoder_reset(VPLDecoder *dec, int width, int height,
                                       int bit_depth) nogil
    void            vpl_decoder_release_surface(VPLDecoder *dec) nogil
    VPLDecodeStatus vpl_decoder_decode(VPLDecoder *dec,
                                        const uint8_t *data, int data_len,
                                        VPLDecodedFrame *frame) nogil
    void            vpl_decoder_get_output_size(VPLDecoder *dec, int *width, int *height)
    int             vpl_decoder_is_hardware(VPLDecoder *dec)
    VPLPixelFormat  vpl_decoder_get_format(VPLDecoder *dec)
    const char*     vpl_decode_status_str(VPLDecodeStatus status)
    int             vpl_decoder_get_last_status(VPLDecoder *dec)
    const char*     vpl_decoder_get_last_error(VPLDecoder *dec)

    ctypedef void (*vpl_log_fn)(const char *msg)
    void            vpl_decode_set_log(vpl_log_fn fn)


cdef void _vpl_log_callback(const char *msg) noexcept with gil:
    log("%s", msg.decode("utf-8", "replace"))


# ── module-level VPLDecoder cache ─────────────────────────────────────
# A single VPLDecoder* that survives Decoder Python-instance churn. The
# consumer (paint_with_video_decoder.do_clean_video_decoder) destroys the
# Python Decoder and creates a fresh one on first frame / encoding change
# / dim change / colorspace change. Without a cache, MFXLoad +
# MFXCreateSession + MFXVideoDECODE_Init (~90 ms) runs on every stream
# change. Parking the underlying VPLDecoder* here lets the next
# init_context reuse it via MFXVideoDECODE_Reset (~150 µs, see
# vpl_decoder_reset).
#
# Sized for one cached context because the typical workload is one
# decoder per window with the occasional bust; concurrent multi-window
# video is rare and each window still gets a fresh create.
#
# bit_depth=8 is hardcoded everywhere: only YUV444P is registered as an
# input colorspace, and vpl_decoder_reset's deferred MFXVideoDECODE_Reset
# trusts that hint as authoritative until DecodeHeader runs. Plumb real
# bit_depth through and partition the cache on it before re-advertising
# Y410 — see memory/vpl_decoder_10bit_registration_gap.md.
cdef VPLDecoder *_cached_context = NULL
_cache_lock = Lock()
# Set True by cleanup_module so a Decoder.clean() running after teardown
# (e.g. a still-held Decoder whose __dealloc__ fires later) destroys its
# context rather than re-parking it into a now-orphaned cache. Cleared
# by init_module so codec-reload across xpra client reconnect resumes
# caching.
_cache_shutdown = False


def init_module(options: dict = None) -> None:
    log("vpl.init_module()")
    if not VPL_ENABLED:
        raise ImportError("oneVPL disabled via XPRA_VPL=0")
    vpl_decode_set_log(_vpl_log_callback)
    cdef VPLDecodeStatus status = vpl_decode_startup()
    if status != VPL_DEC_OK:
        raise ImportError("oneVPL startup failed: %s" %
                          vpl_decode_status_str(status).decode("latin-1"))
    log("vpl: oneVPL startup ok")
    # Re-arm the cache on every init in case a previous reconnect cycle
    # tripped the shutdown flag.
    global _cache_shutdown
    with _cache_lock:
        _cache_shutdown = False


def cleanup_module() -> None:
    # Destroy the cached decoder, if any, and flip the shutdown flag so
    # a later clean() (e.g. on a still-held Decoder whose __dealloc__
    # fires after teardown) destroys instead of re-parking — otherwise
    # the MFX session + DPB stay pinned until process exit. Note that
    # vpl_decode_shutdown itself is a no-op log line: each VPLDecoder
    # owns its own MFXLoader and MFXSession, released by
    # vpl_decoder_destroy independently, so ordering vs. the (empty)
    # global teardown does not matter.
    global _cached_context, _cache_shutdown
    cdef VPLDecoder *to_destroy = NULL
    with _cache_lock:
        _cache_shutdown = True
        if _cached_context != NULL:
            to_destroy = _cached_context
            _cached_context = NULL
    if to_destroy != NULL:
        with nogil:
            vpl_decoder_destroy(to_destroy)
    vpl_decode_shutdown()


def get_version() -> Tuple[int, int]:
    return (1, 0)


def get_type() -> str:
    return "vpl"


def get_info() -> Dict[str, Any]:
    return {
        "version": get_version(),
        "type": "vpl",
    }


def get_encodings() -> Sequence[str]:
    return ("h265", )


def get_min_size(encoding) -> Tuple[int, int]:
    return 64, 64


MAX_WIDTH, MAX_HEIGHT = 16384, 16384


def get_specs() -> Sequence[VideoSpec]:
    # Only 4:4:4 — the MF decoder handles 4:2:0 for all GPU vendors.
    # oneVPL could also do 4:2:0 (Main/Main10 → NV12), which would serve as a
    # fallback if MF fails to load. Not added yet because it would need NV12
    # frame extraction in the C layer and a broader startup probe; the MF
    # decoder has been reliable enough that the added complexity isn't justified.
    #
    # 8-bit only for now. Y410 (10-bit) is deliberately not advertised:
    # only YUV444P is registered at init time, and both the create and the
    # cached-reset paths hardcode bit_depth=8, so a 10-bit stream would be
    # reconfigured against AYUV surfaces. Plumb bit_depth through the
    # Cython wrapper and partition the cache on bd before adding "Y410".
    return (
        VideoSpec(
            encoding="h265",
            input_colorspace="YUV444P",
            output_colorspaces=("AYUV", ),
            has_lossless_mode=False,
            codec_class=Decoder,
            codec_type=get_type(),
            quality=100, speed=100,
            size_efficiency=60,
            setup_cost=0,
            min_w=64, min_h=64,
            width_mask=0xFFFE, height_mask=0xFFFE,
            max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
            # gpu_cost hardcoded since the session is pinned to
            # MFX_IMPL_TYPE_HARDWARE at create time. When adding more
            # codecs (av1/vp9/h264), restructure the startup probe to
            # record per-(codec, profile) hardware status and have this
            # value reflect the actual probe result, since older iGPUs
            # may support some codecs in software only.
            cpu_cost=10, gpu_cost=50,
        ),
    )


cdef class Decoder:
    cdef VPLDecoder *context
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object colorspace
    cdef object encoding

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("vpl.init_context%s", (encoding, width, height, colorspace))
        assert encoding == "h265", "unsupported encoding: %s" % encoding
        # If/when 10-bit support lands (see memory/vpl_decoder_10bit_
        # registration_gap.md), this assertion MUST be updated together
        # with the hardcoded bit_depth=8 below — otherwise a 10-bit
        # stream reusing the cached 8-bit context would be silently
        # mis-decoded by the MFXVideoDECODE_Reset fast path.
        assert colorspace == "YUV444P", "invalid colorspace: %s" % colorspace
        self.encoding = encoding
        self.colorspace = colorspace
        self.width = width
        self.height = height
        self.frames = 0

        cdef VPLDecodeStatus status
        cdef VPLDecoder *cached = NULL
        cdef bint reused = False
        global _cached_context

        # Fast path: pop the cached context (parked by a previous
        # Decoder.clean) and reconfigure it for this stream. The lock is
        # only held across the pointer swap; the (potentially slow)
        # Reset / Destroy / Create calls happen outside it.
        with _cache_lock:
            if _cached_context != NULL:
                cached = _cached_context
                _cached_context = NULL

        if cached != NULL:
            with nogil:
                status = vpl_decoder_reset(cached, width, height, 8)
            if status == VPL_DEC_OK:
                self.context = cached
                reused = True
            else:
                # Reset failed (REALLOC_SURFACE that the C fallback
                # couldn't recover from, MFX_ERR_INCOMPATIBLE_VIDEO_PARAM,
                # ...). Destroy and fall through to a fresh create.
                log.warn("Warning: vpl cached reset(%dx%d) failed: %s",
                         width, height,
                         vpl_decode_status_str(status).decode("latin-1"))
                with nogil:
                    vpl_decoder_destroy(cached)

        if not reused:
            # Cold path: no cached context, or cached Reset failed.
            # bit_depth=8 is a hint; lazy_init re-derives the real
            # value from the bitstream on first decode.
            with nogil:
                status = vpl_decoder_create(&self.context, width, height, 1, 8)
            if status != VPL_DEC_OK:
                raise RuntimeError("failed to create VPL decoder (%dx%d): %s" % (
                    width, height, vpl_decode_status_str(status).decode("latin-1")))

        # The format here reflects the bit-depth HINT passed to create/
        # reset, not the actual stream. lazy_init will update it from
        # DecodeHeader on the first decode call.
        log("vpl %s decoder initialized: hardware=%s, format=%s (hint), reused=%s",
            encoding,
            vpl_decoder_is_hardware(self.context),
            "AYUV" if vpl_decoder_get_format(self.context) == VPL_FMT_AYUV else "Y410",
            reused)

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
        return "vpl"

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        # Early-return on second call: xpra typically calls clean()
        # explicitly on teardown, then Cython __dealloc__ calls it again
        # on GC. First call does the real work; skip the noisy repeat.
        if self.context == NULL:
            return
        cdef VPLDecoder *context = self.context
        cdef VPLDecoder *to_destroy = NULL
        log("vpl close context %#x", <uintptr_t> context)
        self.context = NULL
        # Unmap any locked output surface from the last decode, but
        # leave the decoder otherwise initialized: session + internal
        # surface pool + DPB (~160 MB at 2880x1800 4:4:4) stay alive
        # so the next init_context can reuse this context via
        # vpl_decoder_reset (~150 µs) rather than going through Close +
        # fresh Init (~25 ms).
        with nogil:
            vpl_decoder_release_surface(context)
        global _cached_context
        with _cache_lock:
            if _cache_shutdown or _cached_context != NULL:
                # Either the module is being torn down (cleanup_module
                # ran first), or the cache already holds another
                # context (concurrent stream restart on a second
                # window). Both cases: destroy this one rather than
                # leak it.
                to_destroy = context
            else:
                _cached_context = context
        if to_destroy != NULL:
            with nogil:
                vpl_decoder_destroy(to_destroy)
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
            info["hardware"] = bool(vpl_decoder_is_hardware(self.context))
            fmt = vpl_decoder_get_format(self.context)
            info["pixel_format"] = "AYUV" if fmt == VPL_FMT_AYUV else "Y410" if fmt == VPL_FMT_Y410 else "unknown"
        return info

    def decompress_image(self, data: bytes, options: typedict) -> ImageWrapper:
        cdef VPLDecodedFrame frame
        cdef VPLDecodeStatus status
        cdef const uint8_t *src
        cdef int src_len
        cdef int new_w, new_h

        assert self.context != NULL, "decoder is closed"

        start = monotonic()
        with buffer_context(data) as bc:
            src = <const uint8_t *> (<uintptr_t> int(bc))
            src_len = len(bc)
            with nogil:
                status = vpl_decoder_decode(self.context, src, src_len, &frame)

        if status == VPL_DEC_NEED_MORE_INPUT:
            log("vpl: need more input (buffering)")
            return None

        if status == VPL_DEC_STREAM_CHANGE:
            log("vpl: stream change, updating dimensions")
            vpl_decoder_get_output_size(self.context, &new_w, &new_h)
            self.width = new_w
            self.height = new_h
            return None

        if status != VPL_DEC_OK:
            detail = vpl_decoder_get_last_error(self.context).decode("utf-8", "replace")
            last_sts = vpl_decoder_get_last_status(self.context)
            raise RuntimeError("vpl decode error: %s (detail: %s, sts=%d)" % (
                vpl_decode_status_str(status).decode("latin-1"), detail, last_sts))

        # Update dimensions from the decoded frame (may differ after param change)
        self.width = frame.width
        self.height = frame.height

        # Both AYUV and Y410 are packed 32 bpp — pass directly to the GL shader
        cdef int w = frame.width
        cdef int h = frame.height
        cdef int bpp = 4  # both AYUV and Y410 are 32 bits per pixel

        # extract_frame() advances frame.data to the crop origin, so the
        # mapped surface beyond the last visible pixel is not guaranteed
        # to be readable. Slice exactly through the last row's visible
        # pixels and let ImageWrapper / GL_UNPACK_ROW_LENGTH handle the
        # non-tight stride for upload.
        cdef int payload_bytes = (h - 1) * frame.stride + w * bpp

        copy_start = monotonic()
        pixels = frame.data[:payload_bytes]
        copy_end = monotonic()

        pixel_format = "Y410" if frame.format == VPL_FMT_Y410 else "AYUV"

        self.frames += 1
        cdef int us_copy = int((copy_end - copy_start) * 1000000)
        cdef int us_total = int((copy_end - start) * 1000000)
        log("vpl decoded %8d bytes %dx%d %s in %dms: submit=%dus sync=%dus map=%dus copy=%dus (%.1fMB)",
            src_len, w, h, pixel_format, (us_total + 500) // 1000,
            frame.us_submit, frame.us_sync, frame.us_map, us_copy,
            payload_bytes / 1048576.0)

        full_range = options.boolget("full-range")
        # ImageWrapper handles non-tight rowstrides natively; GL upload uses GL_UNPACK_ROW_LENGTH.
        return ImageWrapper(0, 0, self.width, self.height,
                            (pixels, ), pixel_format, 32, (frame.stride, ), 4,
                            ImageWrapper.PACKED,
                            full_range=full_range)


def selftest(full=False) -> None:
    log("vpl selftest: %s", get_info())
    # Cannot selftest without Intel GPU + HEVC 444 bitstream
    # Just verify the module loads
