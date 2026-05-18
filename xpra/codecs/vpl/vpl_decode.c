/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: Intel oneVPL HEVC 4:4:4 hardware decoder — C implementation.
 * ABOUTME: Manages VPL session, HEVC RExt decode, and AYUV/Y410 frame extraction. */

#include "vpl_decode.h"

#include <vpl/mfxvideo.h>
#include <vpl/mfxdispatcher.h>

#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>

/* ── logging ────────────────────────────────────────────────────────── */

static vpl_log_fn g_log_fn = NULL;

/* XPRA_VPL_RESET_FAST: 0 disables the MFXVideoDECODE_Reset fast path in
   vpl_decoder_reset(), reverting to Close + fresh Init on every pool
   reset. Populated by vpl_decode_startup() on every module init (not
   just the first) so the flag tracks the current env across xpra
   client reconnects. Reader is vpl_decoder_reset on a decoder worker
   thread; unsynchronized-read is defensible because an aligned `int`
   store/load is atomic on x86/ARM (our only targets — oneVPL is
   Intel-only HW), so a torn read is not possible. */
static int reset_fast_enabled = 1;

void vpl_decode_set_log(vpl_log_fn fn) {
    g_log_fn = fn;
}

static void vpl_log(const char *fmt, ...) {
    if (!g_log_fn)
        return;
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    g_log_fn(buf);
}

/* ── timing (Windows QPC) ───────────────────────────────────────────── */

#ifdef _WIN32
#include <windows.h>
static LARGE_INTEGER g_perf_freq = {0};
static long long usec_now(void) {
    LARGE_INTEGER now;
    if (g_perf_freq.QuadPart == 0)
        QueryPerformanceFrequency(&g_perf_freq);
    QueryPerformanceCounter(&now);
    return (long long)(now.QuadPart * 1000000 / g_perf_freq.QuadPart);
}
#else
#include <time.h>
static long long usec_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}
#endif

/* ── decoder state ──────────────────────────────────────────────────── */

struct VPLDecoder {
    mfxLoader       loader;
    mfxSession      session;
    mfxVideoParam   param;
    mfxFrameSurface1 *locked_surface;   /* surface from last decode, awaiting release */
    int             width;
    int             height;
    int             chroma444;
    int             bit_depth;
    VPLPixelFormat  format;
    int             is_hw;
    int             initialized;        /* MFXVideoDECODE_Init has been called */
    /* Set by vpl_decoder_reset when the session is still alive from a
       prior stream but needs reconfiguration for a new one. lazy_init
       runs MFXVideoDECODE_DecodeHeader first (so dec->param carries the
       new bitstream's Profile/Level/PicStruct/aspect/framerate etc.),
       then tries MFXVideoDECODE_Reset before falling back to Close+Init
       on MFX_ERR_REALLOC_SURFACE / MFX_ERR_INCOMPATIBLE_VIDEO_PARAM. We
       cannot Reset at pool-acquire time because caller hints only cover
       dims + bd; leaving prior-stream SPS fields in dec->param makes
       MFX happy at Reset but fails at the first DecodeFrameAsync. */
    int             reset_pending;
    mfxStatus       last_sts;
    char            last_error[128];
};

/* ── error helpers ──────────────────────────────────────────────────── */

static VPLDecodeStatus set_error(VPLDecoder *dec, mfxStatus sts, const char *context) {
    if (dec) {
        dec->last_sts = sts;
        snprintf(dec->last_error, sizeof(dec->last_error),
                 "%s failed: mfxStatus %d", context, (int)sts);
        vpl_log("vpl error: %s", dec->last_error);
    }
    return VPL_DEC_ERROR;
}

const char* vpl_decode_status_str(VPLDecodeStatus status) {
    switch (status) {
        case VPL_DEC_OK:              return "ok";
        case VPL_DEC_NEED_MORE_INPUT: return "need_more_input";
        case VPL_DEC_STREAM_CHANGE:   return "stream_change";
        case VPL_DEC_ERROR:           return "error";
        case VPL_DEC_NOT_AVAILABLE:   return "not_available";
        default:                      return "unknown";
    }
}

int vpl_decoder_get_last_status(VPLDecoder *dec) {
    return dec ? (int)dec->last_sts : 0;
}

const char* vpl_decoder_get_last_error(VPLDecoder *dec) {
    return dec ? dec->last_error : "no decoder";
}

/* ── global init/shutdown ───────────────────────────────────────────── */

/* Try to create a oneVPL session with HEVC decode for a specific profile.
   Returns MFX_ERR_NONE on success (session is closed before returning). */
static mfxStatus probe_hevc_profile(mfxU32 profile) {
    mfxLoader loader;
    mfxConfig cfg_impl, cfg_codec, cfg_profile;
    mfxVariant val;
    mfxSession session;
    mfxStatus sts;

    loader = MFXLoad();
    if (!loader)
        return MFX_ERR_UNSUPPORTED;

    /* oneVPL's canonical pattern is one mfxConfig per filter property.
       Setting multiple properties on a single mfxConfig is not
       guaranteed to AND them across impls; separate configs are the
       documented way to constrain the dispatcher to (HARDWARE AND
       HEVC AND profile=X). Matches Intel's oneVPL sample code. */
    cfg_impl = MFXCreateConfig(loader);
    cfg_codec = MFXCreateConfig(loader);
    cfg_profile = MFXCreateConfig(loader);
    if (!cfg_impl || !cfg_codec || !cfg_profile) {
        MFXUnload(loader);
        return MFX_ERR_UNSUPPORTED;
    }

    memset(&val, 0, sizeof(val));
    val.Type = MFX_VARIANT_TYPE_U32;

    val.Data.U32 = MFX_IMPL_TYPE_HARDWARE;
    sts = MFXSetConfigFilterProperty(cfg_impl,
        (const mfxU8 *)"mfxImplDescription.Impl", val);
    if (sts != MFX_ERR_NONE) { MFXUnload(loader); return sts; }

    val.Data.U32 = MFX_CODEC_HEVC;
    sts = MFXSetConfigFilterProperty(cfg_codec,
        (const mfxU8 *)"mfxImplDescription.mfxDecoderDescription.decoder.CodecID", val);
    if (sts != MFX_ERR_NONE) { MFXUnload(loader); return sts; }

    val.Data.U32 = profile;
    sts = MFXSetConfigFilterProperty(cfg_profile,
        (const mfxU8 *)"mfxImplDescription.mfxDecoderDescription.decoder.decprofile.Profile", val);
    if (sts != MFX_ERR_NONE) { MFXUnload(loader); return sts; }

    sts = MFXCreateSession(loader, 0, &session);
    if (sts == MFX_ERR_NONE)
        MFXClose(session);
    MFXUnload(loader);
    return sts;
}

VPLDecodeStatus vpl_decode_startup(void) {
    /* Probe for an Intel GPU with HEVC 4:4:4 RExt decode support.
       xpra's HEVC 4:4:4 streams use the RExt profile (what nvenc produces),
       so we probe for that specifically. SCC-only hardware (screen-content
       tools: IBC, palette mode) would not be able to decode our streams
       even though it nominally exposes a 4:4:4 capability.

       The GL backing has its own Intel detection (GL_VENDOR string) for DWM
       alpha workarounds, but that checks the rendering GPU, not the media
       engine. A system can have Intel GL without oneVPL (old driver, VM
       passthrough) or oneVPL without Intel GL (headless). Different
       questions, different layers — so we probe independently here. */
    mfxStatus sts;

    /* Re-read the env var on every startup (not just the first) — the
       xpra client reconnect path calls cleanup_module → init_module
       which re-runs vpl_decode_startup in the same process, and the
       user may have flipped XPRA_VPL_RESET_FAST between reconnects. */
    const char *rf = getenv("XPRA_VPL_RESET_FAST");
    reset_fast_enabled = !(rf && rf[0] == '0' && rf[1] == '\0');
    if (!reset_fast_enabled) {
        vpl_log("vpl_decode_startup: MFXVideoDECODE_Reset fast path disabled via XPRA_VPL_RESET_FAST=0");
    }

    sts = probe_hevc_profile(MFX_PROFILE_HEVC_REXT);
    if (sts == MFX_ERR_NONE) {
        vpl_log("vpl_decode_startup: Intel HEVC RExt 444 HW decoder available");
        return VPL_DEC_OK;
    }

    vpl_log("vpl_decode_startup: no Intel HEVC RExt 444 HW decoder found (sts=%d)", (int)sts);
    return VPL_DEC_NOT_AVAILABLE;
}

void vpl_decode_shutdown(void) {
    vpl_log("vpl_decode_shutdown");
}

/* ── release locked surface from previous decode ────────────────────── */

static void release_locked(VPLDecoder *dec) {
    if (dec->locked_surface) {
        dec->locked_surface->FrameInterface->Unmap(dec->locked_surface);
        dec->locked_surface->FrameInterface->Release(dec->locked_surface);
        dec->locked_surface = NULL;
    }
}

/* ── create decoder ─────────────────────────────────────────────────── */

VPLDecodeStatus vpl_decoder_create(VPLDecoder **out, int width, int height,
                                    int chroma444, int bit_depth) {
    mfxStatus sts;
    mfxVariant val;
    VPLDecoder *dec;

    *out = NULL;

    dec = (VPLDecoder *)calloc(1, sizeof(*dec));
    if (!dec)
        return VPL_DEC_ERROR;

    dec->width = width;
    dec->height = height;
    dec->chroma444 = chroma444;
    dec->bit_depth = bit_depth;

    /* determine output format */
    if (chroma444) {
        dec->format = (bit_depth >= 10) ? VPL_FMT_Y410 : VPL_FMT_AYUV;
    } else {
        dec->format = VPL_FMT_UNKNOWN;
        free(dec);
        return VPL_DEC_NOT_AVAILABLE;  /* use MF decoder for 420 */
    }

    /* create loader */
    dec->loader = MFXLoad();
    if (!dec->loader) {
        vpl_log("vpl_decoder_create: MFXLoad failed");
        free(dec);
        return VPL_DEC_NOT_AVAILABLE;
    }

    /* Filters: hardware impl + HEVC codec + RExt profile. One mfxConfig
       per property per the canonical oneVPL pattern — see
       probe_hevc_profile for rationale. Pinning the profile here matches
       the probe so the dispatcher cannot bind this session to a non-RExt
       HEVC implementation on systems that expose multiple. */
    mfxConfig cfg_impl = MFXCreateConfig(dec->loader);
    mfxConfig cfg_codec = MFXCreateConfig(dec->loader);
    mfxConfig cfg_profile = MFXCreateConfig(dec->loader);
    if (!cfg_impl || !cfg_codec || !cfg_profile) {
        vpl_log("vpl_decoder_create: MFXCreateConfig failed");
        MFXUnload(dec->loader);
        free(dec);
        return VPL_DEC_NOT_AVAILABLE;
    }

    memset(&val, 0, sizeof(val));
    val.Type = MFX_VARIANT_TYPE_U32;
    val.Data.U32 = MFX_IMPL_TYPE_HARDWARE;
    sts = MFXSetConfigFilterProperty(cfg_impl,
        (const mfxU8 *)"mfxImplDescription.Impl", val);
    if (sts != MFX_ERR_NONE) {
        vpl_log("vpl_decoder_create: filter Impl failed: %d", (int)sts);
        MFXUnload(dec->loader);
        free(dec);
        return VPL_DEC_NOT_AVAILABLE;
    }

    val.Data.U32 = MFX_CODEC_HEVC;
    sts = MFXSetConfigFilterProperty(cfg_codec,
        (const mfxU8 *)"mfxImplDescription.mfxDecoderDescription.decoder.CodecID", val);
    if (sts != MFX_ERR_NONE) {
        vpl_log("vpl_decoder_create: filter CodecID failed: %d", (int)sts);
        MFXUnload(dec->loader);
        free(dec);
        return VPL_DEC_NOT_AVAILABLE;
    }

    val.Data.U32 = MFX_PROFILE_HEVC_REXT;
    sts = MFXSetConfigFilterProperty(cfg_profile,
        (const mfxU8 *)"mfxImplDescription.mfxDecoderDescription.decoder.decprofile.Profile", val);
    if (sts != MFX_ERR_NONE) {
        vpl_log("vpl_decoder_create: filter Profile failed: %d", (int)sts);
        MFXUnload(dec->loader);
        free(dec);
        return VPL_DEC_NOT_AVAILABLE;
    }

    /* create session */
    sts = MFXCreateSession(dec->loader, 0, &dec->session);
    if (sts != MFX_ERR_NONE) {
        vpl_log("vpl_decoder_create: MFXCreateSession failed: %d (no Intel GPU?)", (int)sts);
        MFXUnload(dec->loader);
        free(dec);
        return VPL_DEC_NOT_AVAILABLE;
    }

    /* configure decode parameters */
    memset(&dec->param, 0, sizeof(dec->param));
    dec->param.mfx.CodecId = MFX_CODEC_HEVC;
    dec->param.mfx.CodecProfile = MFX_PROFILE_HEVC_REXT;
    dec->param.IOPattern = MFX_IOPATTERN_OUT_SYSTEM_MEMORY;
    dec->param.AsyncDepth = 1;

    /* frame info hints — DecodeHeader will overwrite with actual values */
    dec->param.mfx.FrameInfo.Width = (width + 15) & ~15;
    dec->param.mfx.FrameInfo.Height = (height + 15) & ~15;
    dec->param.mfx.FrameInfo.CropW = width;
    dec->param.mfx.FrameInfo.CropH = height;
    dec->param.mfx.FrameInfo.ChromaFormat = MFX_CHROMAFORMAT_YUV444;
    dec->param.mfx.FrameInfo.BitDepthLuma = bit_depth;
    dec->param.mfx.FrameInfo.BitDepthChroma = bit_depth;

    if (bit_depth >= 10) {
        dec->param.mfx.FrameInfo.FourCC = MFX_FOURCC_Y410;
        dec->param.mfx.FrameInfo.Shift = 0;
    } else {
        dec->param.mfx.FrameInfo.FourCC = MFX_FOURCC_AYUV;
    }

    dec->is_hw = 1;  /* we filtered for hardware; will verify after init */

    vpl_log("vpl_decoder_create: session created, %dx%d %s %d-bit",
            width, height, chroma444 ? "444" : "420", bit_depth);

    *out = dec;
    return VPL_DEC_OK;
}

/* ── destroy decoder ────────────────────────────────────────────────── */

void vpl_decoder_destroy(VPLDecoder *dec) {
    if (!dec)
        return;

    vpl_log("vpl_decoder_destroy");
    release_locked(dec);

    if (dec->session) {
        /* The MFX decoder is live when either `initialized` is set OR
           a fast-path Reset is pending: vpl_decoder_reset leaves the
           session's MFX decoder alive while flipping `initialized=0`
           and `reset_pending=1`. Missing that second case would leak
           the decoder's internal surface pool + DPB. */
        if (dec->initialized || dec->reset_pending)
            MFXVideoDECODE_Close(dec->session);
        MFXClose(dec->session);
    }
    if (dec->loader)
        MFXUnload(dec->loader);

    free(dec);
}

/* ── release the last mapped output surface ─────────────────────────── */

void vpl_decoder_release_surface(VPLDecoder *dec) {
    if (!dec)
        return;
    release_locked(dec);
}

/* ── reset decoder for reuse with new dims/bit_depth ────────────────── */

/* Reset dec->param to the same clean-start baseline vpl_decoder_create
   seeds. DecodeHeader on a prior stream may have mutated CodecProfile /
   ChromaFormat / Crop / VUI / FrameRate; leaving those in place makes
   pooled reuse carry stale SPS fields forward — Reset will then either
   fail INCOMPATIBLE_VIDEO_PARAM on the first DecodeFrameAsync, or
   succeed with outdated metadata. */
static void reset_param_baseline(VPLDecoder *dec, int width, int height,
                                  int bit_depth) {
    memset(&dec->param, 0, sizeof(dec->param));
    dec->param.mfx.CodecId = MFX_CODEC_HEVC;
    dec->param.mfx.CodecProfile = MFX_PROFILE_HEVC_REXT;
    dec->param.IOPattern = MFX_IOPATTERN_OUT_SYSTEM_MEMORY;
    dec->param.AsyncDepth = 1;
    dec->param.mfx.FrameInfo.Width = (width + 15) & ~15;
    dec->param.mfx.FrameInfo.Height = (height + 15) & ~15;
    dec->param.mfx.FrameInfo.CropW = width;
    dec->param.mfx.FrameInfo.CropH = height;
    dec->param.mfx.FrameInfo.ChromaFormat = MFX_CHROMAFORMAT_YUV444;
    dec->param.mfx.FrameInfo.BitDepthLuma = bit_depth;
    dec->param.mfx.FrameInfo.BitDepthChroma = bit_depth;
    dec->param.mfx.FrameInfo.FourCC = (bit_depth >= 10) ? MFX_FOURCC_Y410
                                                         : MFX_FOURCC_AYUV;
    dec->param.mfx.FrameInfo.Shift = 0;
}

/* Fallback / slow path for vpl_decoder_reset. Closes the decoder and
   rebuilds dec->param so the next vpl_decoder_decode() call will go
   through lazy_init() (DecodeHeader + fresh Init on the new bitstream).
   Session and loader stay alive, saving MFXLoad + MFXCreateSession on
   each reuse.

   Precondition: caller has already populated dec->{width, height,
   bit_depth, format, is_hw, last_sts, last_error} — those are set in
   vpl_decoder_reset before branching to either the fast path or here. */
static VPLDecodeStatus rebuild_and_close(VPLDecoder *dec, int width, int height,
                                          int bit_depth) {
    /* MFX decoder is live if initialized OR a fast-path Reset is
       pending (see vpl_decoder_destroy's matching gate). */
    if (dec->session && (dec->initialized || dec->reset_pending)) {
        mfxStatus sts = MFXVideoDECODE_Close(dec->session);
        if (sts != MFX_ERR_NONE && sts != MFX_ERR_NOT_INITIALIZED) {
            return set_error(dec, sts, "MFXVideoDECODE_Close");
        }
    }
    dec->initialized = 0;
    dec->reset_pending = 0;

    reset_param_baseline(dec, width, height, bit_depth);

    return VPL_DEC_OK;
}

VPLDecodeStatus vpl_decoder_reset(VPLDecoder *dec, int width, int height,
                                   int bit_depth) {
    if (!dec)
        return VPL_DEC_ERROR;

    vpl_log("vpl_decoder_reset: %dx%d %d-bit (was %dx%d %d-bit)",
            width, height, bit_depth,
            dec->width, dec->height, dec->bit_depth);

    release_locked(dec);

    dec->width = width;
    dec->height = height;
    dec->bit_depth = bit_depth;
    dec->format = (bit_depth >= 10) ? VPL_FMT_Y410 : VPL_FMT_AYUV;
    dec->last_sts = MFX_ERR_NONE;
    dec->last_error[0] = '\0';
    /* Restore the optimistic HW default. A prior stream that hit
       MFX_WRN_PARTIAL_ACCELERATION would have set this to 0; lazy_init
       only flips it 1→0, never the other way, so a stale 0 would stick
       across all later streams on this slot. */
    dec->is_hw = 1;

    /* Fast path setup: if the decoder is already initialized from a
       prior stream and the Reset path is enabled, defer the actual
       MFXVideoDECODE_Reset until DecodeHeader has run on the new
       bitstream. The caller gives us dims + bd but not the SPS-derived
       fields (Profile, Level, PicStruct, AspectRatio, FrameRateExt*,
       max_num_reorder_pics, VUI flags, ...). Leaving the prior
       stream's values for those fields makes MFX accept the Reset but
       then return MFX_ERR_INCOMPATIBLE_VIDEO_PARAM on the first
       DecodeFrameAsync when the new stream's SPS disagrees.

       Flagging reset_pending here and Reset'ing inside lazy_init
       (after DecodeHeader fills dec->param from the real bitstream)
       is the robust way to get the speedup without that mismatch.

       Reset param to the clean-start baseline before lazy_init's
       DecodeHeader runs — otherwise stale SPS / VUI / CropW etc. from
       the previous stream survive into the Reset call when the new
       stream's SPS doesn't explicitly overwrite them. */
    if (dec->initialized && reset_fast_enabled && dec->session) {
        reset_param_baseline(dec, width, height, bit_depth);
        dec->reset_pending = 1;
        dec->initialized = 0;
        return VPL_DEC_OK;
    }

    /* Don't clear reset_pending here — if it was set by a previous
       fast-path-setup call (e.g. pool slot reacquired before any
       frame arrived on the prior stream), rebuild_and_close's Close
       gate needs to see it to avoid leaking the live MFX decoder.
       rebuild_and_close clears both flags after closing. */
    return rebuild_and_close(dec, width, height, bit_depth);
}

/* ── lazy init: parse header from first bitstream, then init decoder ── */

static VPLDecodeStatus lazy_init(VPLDecoder *dec, mfxBitstream *bs) {
    mfxStatus sts;

    /* parse SPS/PPS from bitstream to fill FrameInfo */
    sts = MFXVideoDECODE_DecodeHeader(dec->session, bs, &dec->param);
    if (sts == MFX_ERR_MORE_DATA) {
        vpl_log("vpl lazy_init: need more data for header");
        return VPL_DEC_NEED_MORE_INPUT;
    }
    if (sts != MFX_ERR_NONE && sts != MFX_WRN_PARTIAL_ACCELERATION) {
        return set_error(dec, sts, "DecodeHeader");
    }

    /* verify the stream is actually 444 */
    if (dec->param.mfx.FrameInfo.ChromaFormat != MFX_CHROMAFORMAT_YUV444) {
        vpl_log("vpl lazy_init: stream is not 4:4:4 (chroma=0x%x), use MF decoder instead",
                dec->param.mfx.FrameInfo.ChromaFormat);
        snprintf(dec->last_error, sizeof(dec->last_error),
                 "stream is not 4:4:4 (chroma=0x%x)", dec->param.mfx.FrameInfo.ChromaFormat);
        dec->last_sts = MFX_ERR_UNSUPPORTED;
        return VPL_DEC_ERROR;
    }

    /* update format based on what DecodeHeader found */
    mfxU32 fourcc = dec->param.mfx.FrameInfo.FourCC;
    if (fourcc == MFX_FOURCC_AYUV) {
        dec->format = VPL_FMT_AYUV;
    } else if (fourcc == MFX_FOURCC_Y410) {
        dec->format = VPL_FMT_Y410;
    } else {
        vpl_log("vpl lazy_init: unexpected FourCC 0x%x from DecodeHeader", fourcc);
        /* try to override to our preferred format */
        if (dec->bit_depth >= 10) {
            dec->param.mfx.FrameInfo.FourCC = MFX_FOURCC_Y410;
            dec->format = VPL_FMT_Y410;
        } else {
            dec->param.mfx.FrameInfo.FourCC = MFX_FOURCC_AYUV;
            dec->format = VPL_FMT_AYUV;
        }
    }

    /* Keep the caller-supplied dimensions from vpl_decoder_create — they are
       the real content size from the server's draw packet. DecodeHeader sets
       Width/Height to padded values (e.g. 1643→1664) and may set CropW/CropH
       to the same padded values, so neither is reliable for output sizing. */

    vpl_log("vpl lazy_init: header parsed, %dx%d fourcc=0x%x chroma=0x%x depth=%d",
            dec->width, dec->height,
            dec->param.mfx.FrameInfo.FourCC,
            dec->param.mfx.FrameInfo.ChromaFormat,
            dec->param.mfx.FrameInfo.BitDepthLuma);

    /* Reset fast path. If the previous stream's session is still alive
       (reset_pending set by vpl_decoder_reset), try
       MFXVideoDECODE_Reset against the now-populated dec->param before
       falling back to a full Close+Init. Typical cost on fit: ~1-5 ms.
       Close+Init fallback: ~25 ms, hit when REALLOC_SURFACE (envelope
       needs to grow) or INCOMPATIBLE_VIDEO_PARAM (Profile/Level etc.
       shift beyond what Reset can reconfigure in place). */
    if (dec->reset_pending) {
        long long t0 = usec_now();
        sts = MFXVideoDECODE_Reset(dec->session, &dec->param);
        long long t1 = usec_now();
        dec->reset_pending = 0;
        /* Accept the same success codes Init tolerates below. Reset
           returns MFX_WRN_INCOMPATIBLE_VIDEO_PARAM when the library
           works around a minor mismatch internally — still usable. */
        if (sts == MFX_ERR_NONE
                || sts == MFX_WRN_VIDEO_PARAM_CHANGED
                || sts == MFX_WRN_INCOMPATIBLE_VIDEO_PARAM) {
            vpl_log("vpl lazy_init: reset fast path OK (%lld us, sts=%d)",
                    t1 - t0, (int)sts);
            dec->initialized = 1;
            return VPL_DEC_OK;
        }
        vpl_log("vpl lazy_init: reset fast path failed (sts=%d) after %lld us, Close+Init fallback",
                (int)sts, t1 - t0);
        MFXVideoDECODE_Close(dec->session);
    }

    /* init decoder */
    sts = MFXVideoDECODE_Init(dec->session, &dec->param);
    if (sts != MFX_ERR_NONE && sts != MFX_WRN_PARTIAL_ACCELERATION &&
        sts != MFX_WRN_INCOMPATIBLE_VIDEO_PARAM) {
        return set_error(dec, sts, "MFXVideoDECODE_Init");
    }
    if (sts == MFX_WRN_PARTIAL_ACCELERATION) {
        vpl_log("vpl lazy_init: partial acceleration (software fallback for some operations)");
        dec->is_hw = 0;
    }

    dec->initialized = 1;
    vpl_log("vpl lazy_init: decoder initialized, hw=%d", dec->is_hw);
    return VPL_DEC_OK;
}

/* ── extract pixel data from decoded surface ────────────────────────── */

static VPLDecodeStatus extract_frame(VPLDecoder *dec, mfxFrameSurface1 *surface,
                                      VPLDecodedFrame *frame) {
    mfxStatus sts;
    long long t0, t1;

    t0 = usec_now();
    sts = surface->FrameInterface->Map(surface, MFX_MAP_READ);
    t1 = usec_now();

    if (sts != MFX_ERR_NONE) {
        return set_error(dec, sts, "FrameInterface->Map");
    }

    mfxFrameData *data = &surface->Data;
    mfxFrameInfo *info = &surface->Info;

    /* Pitch is the row stride in bytes */
    int pitch = data->PitchLow + ((int)data->PitchHigh << 16);

    frame->stride = pitch;
    /* Prefer the decoder's stored dimensions (from DecodeHeader CropW/CropH)
       over the surface dimensions, which may be padded to alignment boundaries. */
    frame->width = dec->width;
    frame->height = dec->height;
    frame->format = dec->format;
    frame->us_map = (int)(t1 - t0);

    /* For packed formats, the pixel data starts at the crop origin.
       AYUV: 4 bytes/pixel, Y410: 4 bytes/pixel. */
    int crop_x = info->CropX;
    int crop_y = info->CropY;
    int bpp = 4;  /* both AYUV and Y410 are 32 bpp */

    if (dec->format == VPL_FMT_AYUV) {
        /* AYUV packed: V,U,Y,A per pixel in data->V (or data->B) */
        uint8_t *base = data->V ? data->V : data->Y;
        if (!base) base = data->B;
        if (!base) {
            surface->FrameInterface->Unmap(surface);
            snprintf(dec->last_error, sizeof(dec->last_error), "AYUV: no pixel pointer");
            dec->last_sts = MFX_ERR_NULL_PTR;
            return VPL_DEC_ERROR;
        }
        frame->data = base + crop_y * pitch + crop_x * bpp;
    } else if (dec->format == VPL_FMT_Y410) {
        /* Y410 packed: U10:Y10:V10:A2 per 32-bit word in data->Y410 (or data->Y) */
        uint8_t *base = (uint8_t *)data->Y410;
        if (!base) base = data->Y;
        if (!base) {
            surface->FrameInterface->Unmap(surface);
            snprintf(dec->last_error, sizeof(dec->last_error), "Y410: no pixel pointer");
            dec->last_sts = MFX_ERR_NULL_PTR;
            return VPL_DEC_ERROR;
        }
        frame->data = base + crop_y * pitch + crop_x * bpp;
    } else {
        surface->FrameInterface->Unmap(surface);
        snprintf(dec->last_error, sizeof(dec->last_error), "unsupported format %d", dec->format);
        dec->last_sts = MFX_ERR_UNSUPPORTED;
        return VPL_DEC_ERROR;
    }

    /* check nominal range */
    frame->full_range = 0;  /* oneVPL doesn't expose this directly; rely on encoder hint */

    /* keep surface mapped; store for cleanup on next decode call */
    surface->FrameInterface->AddRef(surface);
    dec->locked_surface = surface;

    vpl_log("vpl extract: %dx%d stride=%d fmt=%s map=%dus",
            frame->width, frame->height, pitch,
            dec->format == VPL_FMT_AYUV ? "AYUV" : "Y410",
            frame->us_map);

    return VPL_DEC_OK;
}

/* ── decode one access unit ─────────────────────────────────────────── */

VPLDecodeStatus vpl_decoder_decode(VPLDecoder *dec,
                                    const uint8_t *data, int data_len,
                                    VPLDecodedFrame *frame) {
    mfxStatus sts;
    mfxBitstream bs;
    mfxFrameSurface1 *surface_out = NULL;
    mfxSyncPoint syncp = NULL;
    long long t0, t1, t2;
    VPLDecodeStatus vst;
    int retries;

    memset(frame, 0, sizeof(*frame));
    release_locked(dec);

    /* set up bitstream */
    memset(&bs, 0, sizeof(bs));
    bs.Data = (mfxU8 *)data;
    bs.DataLength = data_len;
    bs.MaxLength = data_len;
    bs.DataFlag = MFX_BITSTREAM_COMPLETE_FRAME;

    /* lazy init on first call: parse header and init decoder */
    if (!dec->initialized) {
        vst = lazy_init(dec, &bs);
        if (vst != VPL_DEC_OK)
            return vst;
    }

    /* submit compressed data */
    t0 = usec_now();
    retries = 0;

retry:
    sts = MFXVideoDECODE_DecodeFrameAsync(dec->session, &bs, NULL,
                                           &surface_out, &syncp);
    t1 = usec_now();

    if (sts == MFX_WRN_DEVICE_BUSY) {
        if (retries++ < 100) {
#ifdef _WIN32
            Sleep(1);
#else
            usleep(1000);
#endif
            goto retry;
        }
        return set_error(dec, sts, "DecodeFrameAsync(device_busy)");
    }

    if (sts == MFX_ERR_MORE_DATA) {
        frame->us_submit = (int)(t1 - t0);
        return VPL_DEC_NEED_MORE_INPUT;
    }

    if (sts == MFX_ERR_MORE_SURFACE) {
        /* shouldn't happen with internal allocation, but handle gracefully */
        vpl_log("vpl decode: MFX_ERR_MORE_SURFACE (unexpected with internal alloc)");
        frame->us_submit = (int)(t1 - t0);
        return VPL_DEC_NEED_MORE_INPUT;
    }

    if (sts == MFX_WRN_VIDEO_PARAM_CHANGED) {
        /* sequence header changed; update our cached dimensions */
        mfxVideoParam new_param;
        memset(&new_param, 0, sizeof(new_param));
        new_param.mfx.CodecId = MFX_CODEC_HEVC;
        MFXVideoDECODE_GetVideoParam(dec->session, &new_param);
        dec->width = new_param.mfx.FrameInfo.CropW;
        dec->height = new_param.mfx.FrameInfo.CropH;
        if (dec->width == 0)
            dec->width = new_param.mfx.FrameInfo.Width;
        if (dec->height == 0)
            dec->height = new_param.mfx.FrameInfo.Height;
        vpl_log("vpl decode: param changed, new size %dx%d", dec->width, dec->height);

        /* the decode may still have produced a frame */
        if (!surface_out || !syncp) {
            frame->us_submit = (int)(t1 - t0);
            return VPL_DEC_STREAM_CHANGE;
        }
        /* fall through to sync + extract */
    }

    if (sts != MFX_ERR_NONE && sts != MFX_WRN_VIDEO_PARAM_CHANGED) {
        return set_error(dec, sts, "DecodeFrameAsync");
    }

    if (!surface_out || !syncp) {
        frame->us_submit = (int)(t1 - t0);
        return VPL_DEC_NEED_MORE_INPUT;
    }

    /* sync: wait for GPU decode to finish */
    sts = surface_out->FrameInterface->Synchronize(surface_out, 5000);
    t2 = usec_now();

    if (sts != MFX_ERR_NONE) {
        surface_out->FrameInterface->Release(surface_out);
        return set_error(dec, sts, "Synchronize");
    }

    frame->us_submit = (int)(t1 - t0);
    frame->us_sync = (int)(t2 - t1);

    /* extract pixels */
    vst = extract_frame(dec, surface_out, frame);

    /* release the async reference (extract_frame AddRef'd if it needs to keep it) */
    surface_out->FrameInterface->Release(surface_out);

    return vst;
}

/* ── queries ────────────────────────────────────────────────────────── */

void vpl_decoder_get_output_size(VPLDecoder *dec, int *width, int *height) {
    if (dec) {
        *width = dec->width;
        *height = dec->height;
    } else {
        *width = 0;
        *height = 0;
    }
}

int vpl_decoder_is_hardware(VPLDecoder *dec) {
    return dec ? dec->is_hw : 0;
}

VPLPixelFormat vpl_decoder_get_format(VPLDecoder *dec) {
    return dec ? dec->format : VPL_FMT_UNKNOWN;
}
