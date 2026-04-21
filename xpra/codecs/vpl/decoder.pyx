# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: Intel oneVPL HEVC 4:4:4 hardware decoder for Windows.
# ABOUTME: Wraps the C vpl_decode API; outputs AYUV for the GL shader pipeline.

#cython: wraparound=False

import os
from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec
from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger
log = Logger("decoder", "vpl")

VPL_ENABLED = os.environ.get("XPRA_VPL", "1") != "0"
# XPRA_VPL_POOL=0 forces direct create/destroy on every Decoder, bypassing
# the decoder pool entirely. Rollback escape hatch for the pooling feature.
# Cleared at init_module time if reaper scheduling fails, so we revert to
# direct create/destroy rather than accumulating decoders without trimming.
VPL_POOL_ENABLED = os.environ.get("XPRA_VPL_POOL", "1") != "0"

# GLib source id of the scheduled reaper, so cleanup_module can remove it
# cleanly and reconnect doesn't leave a ghost source ticking until the
# next reap (which would no-op and self-drop on shutdown, but still).
_reap_source_id = 0

from libc.stdint cimport uint8_t, uintptr_t
from libc.string cimport memcpy
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


# ── raw C-level helpers exposed to xpra.codecs.vpl.pool ───────────────
# The pool stores the integer address of the VPLDecoder pointer; Python
# never dereferences it. All three helpers raise on VPL failure so
# DecoderPool's reset-failure retry logic can trigger.
#
# _vpl_pool_create raises VPLNotAvailable for the probe-miss case
# (Intel iGPU absent, driver too old) so init_context can re-raise as
# ImportError to let the codec dispatcher fall through to the next
# decoder. Other failures surface as RuntimeError.


class VPLNotAvailable(RuntimeError):
    """Raised by _vpl_pool_create when the oneVPL runtime reports the
    decoder is not available (typically no Intel GPU or RExt profile)."""


# Bit-depth hint passed to the C layer on create/reset. lazy_init re-runs
# DecodeHeader from the actual bitstream on every stream start, so this
# value only controls the INITIAL surface allocation — a slot seeded here
# as 8-bit decodes 10-bit streams fine (and vice versa) after the first
# decode triggers re-Init with the real params.
DEF VPL_POOL_BIT_DEPTH_HINT = 8


def _vpl_pool_create(int width, int height, object key) -> int:
    # ``key`` is a caller opaque (see xpra.codecs.vpl.pool.VPL_POOL_KEY);
    # we don't partition by it here.
    cdef VPLDecoder *dec = NULL
    cdef VPLDecodeStatus status
    cdef int bit_depth = VPL_POOL_BIT_DEPTH_HINT
    with nogil:
        status = vpl_decoder_create(&dec, width, height, 1, bit_depth)
    if status == VPL_DEC_NOT_AVAILABLE:
        raise VPLNotAvailable(
            "oneVPL HEVC 444 decoder not available (no Intel GPU?)")
    if status != VPL_DEC_OK or dec is NULL:
        raise RuntimeError("vpl_decoder_create(%dx%d) failed: %s" %
                           (width, height,
                            vpl_decode_status_str(status).decode("latin-1")))
    return <size_t>dec


def _vpl_pool_reset(addr: int, int width, int height, object key) -> None:
    # bit_depth is hardcoded to 8 because the only colorspace
    # init_context accepts today is YUV444P (8-bit). The
    # MFXVideoDECODE_Reset fast path inside vpl_decoder_reset trusts
    # this hint as authoritative for new-stream params — adding 10-bit
    # support (unblocking the Y410 path) requires plumbing real bit_depth
    # through here AND partitioning the pool key on bit depth, otherwise
    # a 10-bit stream would be decoded against an 8-bit AYUV slot.
    # Tracked in memory/vpl_decoder_10bit_registration_gap.md.
    cdef VPLDecoder *dec = <VPLDecoder*><size_t>addr
    cdef VPLDecodeStatus status
    cdef int bit_depth = VPL_POOL_BIT_DEPTH_HINT
    with nogil:
        status = vpl_decoder_reset(dec, width, height, bit_depth)
    if status != VPL_DEC_OK:
        raise RuntimeError("vpl_decoder_reset(%dx%d) failed: %s" %
                           (width, height,
                            vpl_decode_status_str(status).decode("latin-1")))


def _vpl_pool_destroy(addr: int) -> None:
    cdef VPLDecoder *dec = <VPLDecoder*><size_t>addr
    with nogil:
        vpl_decoder_destroy(dec)


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
    global VPL_POOL_ENABLED
    # Re-read the env var on every init_module call so a prior reaper-
    # scheduling failure doesn't permanently disable pooling across
    # client reconnects (unload_codecs keeps the module in sys.modules,
    # so the flag would otherwise stick at False).
    VPL_POOL_ENABLED = os.environ.get("XPRA_VPL_POOL", "1") != "0"
    if VPL_POOL_ENABLED:
        from xpra.codecs.vpl import pool as vpl_pool
        vpl_pool.init_pool(_vpl_pool_create, _vpl_pool_reset, _vpl_pool_destroy)
        # Schedule the reaper on the GLib main loop so idle decoders past
        # XPRA_VPL_IDLE_TIMEOUT and slots over XPRA_VPL_POOL_SIZE actually
        # get trimmed. Without this, the pool grows unbounded for the
        # process lifetime.
        global _reap_source_id
        try:
            from xpra.os_util import gi_import
            glib = gi_import("GLib")
            # Remove any stale source first (double-init without an
            # intervening cleanup_module, e.g. codec selftest).
            if _reap_source_id:
                try:
                    glib.source_remove(_reap_source_id)
                except Exception:  # pylint: disable=broad-except
                    pass
                _reap_source_id = 0
            _reap_source_id = glib.timeout_add(10 * 1000,
                                               vpl_pool.get_pool().reap)
            log("vpl: decoder pool initialized, reaper scheduled every 10s")
        except Exception as e:
            # No reaper means unbounded growth. Shut down the pool and
            # fall back to direct create/destroy for every Decoder.
            log.warn("Warning: failed to schedule VPL pool reaper: %s", e)
            log.warn(" falling back to unpooled create/destroy")
            vpl_pool.shutdown()
            VPL_POOL_ENABLED = False


def cleanup_module() -> None:
    # Shut down the decoder pool first so cached/queued decoders destroy
    # cleanly. Safe to call even if nothing has initialized the pool.
    #
    # Order note: vpl_decode_shutdown() is a no-op log line — there is no
    # shared oneVPL runtime state. Each VPLDecoder owns its own MFXLoader
    # and MFXSession, released by vpl_decoder_destroy() independently. So
    # a pooled decoder that outlives cleanup_module (held across teardown
    # then released) can still destroy correctly.
    global _reap_source_id
    if _reap_source_id:
        try:
            from xpra.os_util import gi_import
            gi_import("GLib").source_remove(_reap_source_id)
        except Exception as e:
            log.warn("Warning: failed to remove VPL reaper source: %s", e)
        _reap_source_id = 0
    from xpra.codecs.vpl import pool as vpl_pool
    vpl_pool.shutdown()
    vpl_decode_shutdown()


def get_version() -> Tuple[int, int]:
    return (1, 0)


def get_type() -> str:
    return "vpl"


def get_info() -> Dict[str, Any]:
    return {
        "version": get_version(),
        "type": "oneVPL",
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
    # only YUV444P is registered at init time, and the pool reset path hardcodes
    # bit_depth=8, so a 10-bit stream would be reconfigured against AYUV surfaces.
    # Plumb bit_depth through the Cython wrapper and partition the pool key on
    # bd before adding "Y410" here.
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
    # When pooling is enabled (XPRA_VPL_POOL=1), ``_slot`` holds the
    # CachedDecoder this instance acquired from xpra.codecs.vpl.pool.
    # ``clean`` returns it to the pool instead of destroying; the pool's
    # reset_fn is called on the next init_context that hits this slot.
    # None if pool is disabled or the slot has already been released.
    cdef object _slot

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("vpl.init_context%s", (encoding, width, height, colorspace))
        assert encoding == "h265", "unsupported encoding: %s" % encoding
        # If/when 10-bit support lands (see memory/vpl_decoder_10bit_
        # registration_gap.md), this assertion MUST be updated together
        # with _vpl_pool_reset's hardcoded VPL_POOL_BIT_DEPTH_HINT and
        # the pool key partitioning — otherwise a 10-bit stream routed
        # to an 8-bit-configured pool slot would be silently mis-decoded
        # by the MFXVideoDECODE_Reset fast path.
        assert colorspace == "YUV444P", "invalid colorspace: %s" % colorspace
        self.encoding = encoding
        self.colorspace = colorspace
        self.width = width
        self.height = height
        self.frames = 0
        cdef VPLDecodeStatus status
        if VPL_POOL_ENABLED:
            from xpra.codecs.vpl import pool as vpl_pool
            # VPLNotAvailable inherits from RuntimeError, which
            # paint_with_video_decoder catches to fall through to the
            # next decoder in the dispatcher loop.
            self._slot = vpl_pool.acquire(width, height)
            self.context = <VPLDecoder*><size_t>self._slot.handle
        else:
            # bit_depth=8 is just a hint; lazy_init re-derives the real
            # value from the bitstream on first decode.
            status = vpl_decoder_create(&self.context, width, height, 1, 8)
            if status != VPL_DEC_OK:
                raise RuntimeError("failed to create VPL decoder (%dx%d): %s" % (
                    width, height, vpl_decode_status_str(status).decode("latin-1")))
        # The format here reflects the bit-depth HINT passed to create/
        # reset, not the actual stream. lazy_init will update it from
        # DecodeHeader on the first decode call.
        log("vpl %s decoder initialized: hardware=%s, format=%s (hint), pooled=%s",
            encoding,
            vpl_decoder_is_hardware(self.context),
            "AYUV" if vpl_decoder_get_format(self.context) == VPL_FMT_AYUV else "Y410",
            VPL_POOL_ENABLED)

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
        if self.context == NULL and self._slot is None:
            return
        log("vpl close context %#x (pooled=%s)",
            <uintptr_t> self.context, self._slot is not None)
        cdef VPLDecoder *context = self.context
        self.context = NULL
        slot = self._slot
        self._slot = None
        if slot is not None:
            # Unmap any locked output surface from the last decode, but
            # leave the decoder initialized (session + internal surface
            # pool + DPB ~160 MB at 2880x1800 4:4:4 all stay alive). The
            # next pool.acquire() calls vpl_decoder_reset() which uses
            # MFXVideoDECODE_Reset to reconfigure in place — if we
            # Close here, that fast path is forced to fall back to
            # Close+Init on every reuse. The reaper reclaims the memory
            # once the slot has been idle past XPRA_VPL_IDLE_TIMEOUT.
            if context:
                with nogil:
                    vpl_decoder_release_surface(context)
            # Return the decoder to the pool for reuse. The pool owns the
            # VPLDecoder* handle now; don't destroy it here.
            from xpra.codecs.vpl import pool as vpl_pool
            vpl_pool.release(slot)
        elif context:
            # Non-pooled (XPRA_VPL_POOL=0): we own the handle, destroy it.
            with nogil:
                vpl_decoder_destroy(context)
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
        cdef uint8_t *dst
        cdef int y_row

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
        cdef int row_bytes = w * bpp

        copy_start = monotonic()
        if frame.stride == row_bytes:
            pixels = frame.data[:row_bytes * h]
        else:
            # stride != width*bpp due to padding; must compact rows
            buf = bytearray(row_bytes * h)
            dst = <uint8_t *> buf
            with nogil:
                for y_row in range(h):
                    memcpy(dst + y_row * row_bytes,
                           frame.data + y_row * frame.stride,
                           row_bytes)
            pixels = bytes(buf)
        copy_end = monotonic()

        pixel_format = "Y410" if frame.format == VPL_FMT_Y410 else "AYUV"

        self.frames += 1
        cdef int us_copy = int((copy_end - copy_start) * 1000000)
        cdef int us_total = int((copy_end - start) * 1000000)
        log("vpl decoded %8d bytes %dx%d %s in %dms: submit=%dus sync=%dus map=%dus copy=%dus (%.1fMB)",
            src_len, w, h, pixel_format, (us_total + 500) // 1000,
            frame.us_submit, frame.us_sync, frame.us_map, us_copy,
            (row_bytes * h) / 1048576.0)

        full_range = options.boolget("full-range")
        # Wrap as single-plane tuple so the GL planar texture upload path works
        return ImageWrapper(0, 0, self.width, self.height,
                            (pixels, ), pixel_format, 32, (row_bytes, ), 4,
                            ImageWrapper.PACKED,
                            full_range=full_range)


def selftest(full=False) -> None:
    log("vpl selftest: %s", get_info())
    # Cannot selftest without Intel GPU + HEVC 444 bitstream
    # Just verify the module loads
