/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: Intel oneVPL H.264 encoder - C implementation.
 * ABOUTME: Manages VPL session, NV12 staging, and AVC bitstream extraction. */

#include "vpl_encode.h"

#include <vpl/mfxvideo.h>
#include <vpl/mfxdispatcher.h>

#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>

#ifdef _WIN32
#include <windows.h>
#include <malloc.h>
#endif

static vpl_log_fn g_log_fn = NULL;

void vpl_encode_set_log(vpl_log_fn fn) {
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

#ifdef _WIN32
static LARGE_INTEGER g_perf_freq = {0};
static long long usec_now(void) {
    LARGE_INTEGER now;
    if (g_perf_freq.QuadPart == 0)
        QueryPerformanceFrequency(&g_perf_freq);
    QueryPerformanceCounter(&now);
    return (long long)(now.QuadPart * 1000000 / g_perf_freq.QuadPart);
}
static void sleep_1ms(void) {
    Sleep(1);
}
static void *aligned_malloc32(size_t size) {
    return _aligned_malloc(size, 32);
}
static void aligned_free32(void *ptr) {
    _aligned_free(ptr);
}
#else
#include <time.h>
static long long usec_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}
static void sleep_1ms(void) {
    const struct timespec ts = {
        .tv_sec = 0,
        .tv_nsec = 1000 * 1000,
    };
    nanosleep(&ts, NULL);
}
static void *aligned_malloc32(size_t size) {
    void *ptr = NULL;
    if (posix_memalign(&ptr, 32, size) != 0)
        return NULL;
    return ptr;
}
static void aligned_free32(void *ptr) {
    free(ptr);
}
#endif

struct VPLEncoder {
    mfxLoader       loader;
    mfxSession      session;
    mfxVideoParam   param;
    mfxFrameSurface1 surface;
    uint8_t        *surface_data;
    size_t          surface_size;
    uint8_t        *bitstream_data;
    size_t          bitstream_size;
    int             width;
    int             height;
    int             pitch;
    int             frames;
    int             quality;
    int             speed;
    VPLEncodeProfile profile;
    int             use_icq;        /* 1 if ICQ rate-control is in use; 0 = CQP */
    int             next_qp;        /* per-frame mfxEncodeCtrl.QP override (CQP only); 0 = use configured */
    int             is_hw;
    mfxSyncPoint    pending_sync;   /* syncp awaiting drain; non-NULL only on the
                                       error path between submit and a clean sync */
    mfxStatus       last_sts;
    char            last_error[128];
};

static mfxU16 vpl_profile_id(VPLEncodeProfile profile) {
    switch (profile) {
    case VPL_ENC_PROFILE_CONSTRAINED_BASELINE:
        return MFX_PROFILE_AVC_CONSTRAINED_BASELINE;
    case VPL_ENC_PROFILE_MAIN:
        return MFX_PROFILE_AVC_MAIN;
    case VPL_ENC_PROFILE_HIGH:
        return MFX_PROFILE_AVC_HIGH;
    default:
        return 0;
    }
}

static int roundup(int n, int m) {
    return (n + m - 1) & ~(m - 1);
}

static int clamp_int(int value, int low, int high) {
    if (value < low)
        return low;
    if (value > high)
        return high;
    return value;
}

static VPLEncodeStatus set_error(VPLEncoder *enc, mfxStatus sts, const char *context) {
    if (enc) {
        enc->last_sts = sts;
        snprintf(enc->last_error, sizeof(enc->last_error),
                 "%s failed: mfxStatus %d", context, (int)sts);
        vpl_log("vpl encode error: %s", enc->last_error);
    }
    return VPL_ENC_ERROR;
}

const char* vpl_encode_status_str(VPLEncodeStatus status) {
    switch (status) {
        case VPL_ENC_OK:              return "ok";
        case VPL_ENC_NEED_MORE_INPUT: return "need_more_input";
        case VPL_ENC_ERROR:           return "error";
        case VPL_ENC_NOT_AVAILABLE:   return "not_available";
        default:                      return "unknown";
    }
}

static mfxStatus make_h264_session(mfxLoader *loader_out, mfxSession *session_out) {
    mfxLoader loader;
    mfxConfig cfg_impl, cfg_codec;
    mfxVariant val;
    mfxStatus sts;

    *loader_out = NULL;
    *session_out = NULL;

    loader = MFXLoad();
    if (!loader)
        return MFX_ERR_UNSUPPORTED;

    cfg_impl = MFXCreateConfig(loader);
    cfg_codec = MFXCreateConfig(loader);
    if (!cfg_impl || !cfg_codec) {
        MFXUnload(loader);
        return MFX_ERR_UNSUPPORTED;
    }

    memset(&val, 0, sizeof(val));
    val.Type = MFX_VARIANT_TYPE_U32;

    val.Data.U32 = MFX_IMPL_TYPE_HARDWARE;
    sts = MFXSetConfigFilterProperty(cfg_impl,
        (const mfxU8 *)"mfxImplDescription.Impl", val);
    if (sts != MFX_ERR_NONE) {
        MFXUnload(loader);
        return sts;
    }

    val.Data.U32 = MFX_CODEC_AVC;
    sts = MFXSetConfigFilterProperty(cfg_codec,
        (const mfxU8 *)"mfxImplDescription.mfxEncoderDescription.encoder.CodecID", val);
    if (sts != MFX_ERR_NONE) {
        MFXUnload(loader);
        return sts;
    }

    sts = MFXCreateSession(loader, 0, session_out);
    if (sts != MFX_ERR_NONE) {
        MFXUnload(loader);
        return sts;
    }

    *loader_out = loader;
    return MFX_ERR_NONE;
}

VPLEncodeStatus vpl_encode_startup(void) {
    mfxLoader loader = NULL;
    mfxSession session = NULL;
    mfxStatus sts = make_h264_session(&loader, &session);
    if (sts != MFX_ERR_NONE) {
        vpl_log("vpl encode startup: no hardware AVC encoder, sts=%d", (int)sts);
        return VPL_ENC_NOT_AVAILABLE;
    }
    MFXClose(session);
    MFXUnload(loader);
    vpl_log("vpl encode startup: hardware AVC encoder available");
    return VPL_ENC_OK;
}

void vpl_encode_shutdown(void) {
    vpl_log("vpl encode shutdown");
}

static void fill_params(VPLEncoder *enc, mfxVideoParam *param, int use_icq) {
    int q = 51 - (clamp_int(enc->quality, 0, 100) * 50 + 50) / 100;
    q = clamp_int(q, 1, 51);

    memset(param, 0, sizeof(*param));
    param->IOPattern = MFX_IOPATTERN_IN_SYSTEM_MEMORY;
    param->AsyncDepth = 1;

    param->mfx.CodecId = MFX_CODEC_AVC;
    param->mfx.CodecProfile = vpl_profile_id(enc->profile);
    param->mfx.TargetUsage = 1 + (clamp_int(enc->speed, 0, 100) * 6 + 50) / 100;
    param->mfx.GopPicSize = 0;
    param->mfx.GopRefDist = 1;
    param->mfx.IdrInterval = 0;
    param->mfx.NumRefFrame = 1;
    param->mfx.FrameInfo.FourCC = MFX_FOURCC_NV12;
    param->mfx.FrameInfo.ChromaFormat = MFX_CHROMAFORMAT_YUV420;
    param->mfx.FrameInfo.PicStruct = MFX_PICSTRUCT_PROGRESSIVE;
    param->mfx.FrameInfo.CropX = 0;
    param->mfx.FrameInfo.CropY = 0;
    param->mfx.FrameInfo.CropW = enc->width;
    param->mfx.FrameInfo.CropH = enc->height;
    param->mfx.FrameInfo.Width = roundup(enc->width, 16);
    param->mfx.FrameInfo.Height = roundup(enc->height, 16);
    param->mfx.FrameInfo.BitDepthLuma = 8;
    param->mfx.FrameInfo.BitDepthChroma = 8;
    param->mfx.FrameInfo.FrameRateExtN = 30;
    param->mfx.FrameInfo.FrameRateExtD = 1;

    if (use_icq) {
        param->mfx.RateControlMethod = MFX_RATECONTROL_ICQ;
        param->mfx.ICQQuality = q;
    } else {
        param->mfx.RateControlMethod = MFX_RATECONTROL_CQP;
        param->mfx.QPI = q;
        param->mfx.QPP = q;
        param->mfx.QPB = q;
    }
}

static VPLEncodeStatus allocate_buffers(VPLEncoder *enc) {
    size_t surface_size = (size_t)enc->pitch * enc->height * 3 / 2;
    size_t bs_size = (size_t)enc->param.mfx.BufferSizeInKB * 1000;
    size_t fallback = (size_t)enc->width * enc->height * 4 + 1024 * 1024;
    if (bs_size < fallback)
        bs_size = fallback;

    enc->surface_data = (uint8_t *)aligned_malloc32(surface_size);
    enc->bitstream_data = (uint8_t *)aligned_malloc32(bs_size);
    if (!enc->surface_data || !enc->bitstream_data) {
        snprintf(enc->last_error, sizeof(enc->last_error), "failed to allocate encoder buffers");
        enc->last_sts = MFX_ERR_MEMORY_ALLOC;
        return VPL_ENC_ERROR;
    }

    enc->surface_size = surface_size;
    enc->bitstream_size = bs_size;
    memset(enc->surface_data, 0, surface_size);
    return VPL_ENC_OK;
}

VPLEncodeStatus vpl_encoder_create(VPLEncoder **out, int width, int height,
                                   int quality, int speed, VPLEncodeProfile profile) {
    VPLEncoder *enc;
    mfxStatus sts;
    int use_icq;
    int attempt;

    if (!out)
        return VPL_ENC_ERROR;
    *out = NULL;

    if (width <= 0 || height <= 0 || (width & 1) || (height & 1) ||
        !vpl_profile_id(profile))
        return VPL_ENC_ERROR;

    enc = (VPLEncoder *)calloc(1, sizeof(VPLEncoder));
    if (!enc)
        return VPL_ENC_ERROR;

    enc->width = width;
    enc->height = height;
    enc->pitch = roundup(width, 32);
    enc->quality = quality;
    enc->speed = speed;
    enc->profile = profile;
    enc->is_hw = 1;
    enc->last_sts = MFX_ERR_NONE;

    sts = make_h264_session(&enc->loader, &enc->session);
    if (sts != MFX_ERR_NONE) {
        set_error(enc, sts, "MFXCreateSession");
        vpl_encoder_destroy(enc);
        return VPL_ENC_NOT_AVAILABLE;
    }

    /* Do not probe ICQ with MFXVideoENCODE_Query here: some libmfxhw
       versions crash inside the driver on a fresh VPL encode session.
       Try ICQ directly first, then fall back to broadly supported CQP. */
    sts = MFX_ERR_UNSUPPORTED;
    for (attempt = 0; attempt < 2; attempt++) {
        use_icq = (attempt == 0);
        enc->use_icq = use_icq;
        fill_params(enc, &enc->param, use_icq);
        vpl_log("vpl encoder create: %dx%d quality=%d speed=%d profile=%d rc=%s",
                width, height, quality, speed, (int)profile, use_icq ? "ICQ" : "CQP");

        sts = MFXVideoENCODE_Init(enc->session, &enc->param);
        if (sts == MFX_ERR_NONE || sts == MFX_WRN_PARTIAL_ACCELERATION ||
            sts == MFX_WRN_INCOMPATIBLE_VIDEO_PARAM) {
            break;
        }
        if (use_icq)
            vpl_log("vpl encoder ICQ init failed: mfxStatus %d, trying CQP", (int)sts);
    }
    if (sts != MFX_ERR_NONE && sts != MFX_WRN_PARTIAL_ACCELERATION &&
        sts != MFX_WRN_INCOMPATIBLE_VIDEO_PARAM) {
        set_error(enc, sts, "MFXVideoENCODE_Init");
        vpl_encoder_destroy(enc);
        return VPL_ENC_ERROR;
    }
    if (sts == MFX_WRN_PARTIAL_ACCELERATION)
        enc->is_hw = 0;

    MFXVideoENCODE_GetVideoParam(enc->session, &enc->param);
    if (allocate_buffers(enc) != VPL_ENC_OK) {
        vpl_encoder_destroy(enc);
        return VPL_ENC_ERROR;
    }

    memset(&enc->surface, 0, sizeof(enc->surface));
    enc->surface.Info = enc->param.mfx.FrameInfo;
    enc->surface.Data.MemType = MFX_MEMTYPE_SYSTEM_MEMORY;
    enc->surface.Data.PitchLow = enc->pitch & 0xffff;
    enc->surface.Data.PitchHigh = (enc->pitch >> 16) & 0xffff;
    enc->surface.Data.Y = enc->surface_data;
    enc->surface.Data.UV = enc->surface_data + (size_t)enc->pitch * enc->height;

    *out = enc;
    return VPL_ENC_OK;
}

void vpl_encoder_destroy(VPLEncoder *enc) {
    if (!enc)
        return;
    if (enc->session) {
        /* Drain any frame still owned by the async scheduler before we free the
           bitstream/surface buffers it copies into. MFXVideoENCODE_Close does
           not reliably wait for a sync point the app never retrieved, which is
           how a teardown during resize can race the worker thread. */
        if (enc->pending_sync) {
            MFXVideoCORE_SyncOperation(enc->session, enc->pending_sync, 1000);
            enc->pending_sync = NULL;
        }
        MFXVideoENCODE_Close(enc->session);
        MFXClose(enc->session);
    }
    if (enc->loader)
        MFXUnload(enc->loader);
    aligned_free32(enc->surface_data);
    aligned_free32(enc->bitstream_data);
    free(enc);
}

static void copy_nv12(VPLEncoder *enc,
                      const uint8_t *y, int y_stride,
                      const uint8_t *uv, int uv_stride) {
    int row;
    uint8_t *dst_y = enc->surface.Data.Y;
    uint8_t *dst_uv = enc->surface.Data.UV;

    for (row = 0; row < enc->height; row++) {
        memcpy(dst_y + (size_t)row * enc->pitch,
               y + (size_t)row * y_stride,
               enc->width);
    }
    for (row = 0; row < enc->height / 2; row++) {
        memcpy(dst_uv + (size_t)row * enc->pitch,
               uv + (size_t)row * uv_stride,
               enc->width);
    }
}

static VPLEncodeFrameType frame_type_from_mfx(mfxU16 frame_type) {
    if (frame_type & MFX_FRAMETYPE_IDR)
        return VPL_ENC_FRAME_IDR;
    if (frame_type & MFX_FRAMETYPE_I)
        return VPL_ENC_FRAME_I;
    if (frame_type & MFX_FRAMETYPE_P)
        return VPL_ENC_FRAME_P;
    return VPL_ENC_FRAME_UNKNOWN;
}

static VPLEncodeStatus do_encode(VPLEncoder *enc, mfxFrameSurface1 *surface,
                                 int force_idr, VPLEncodedFrame *frame) {
    mfxBitstream bs;
    mfxEncodeCtrl ctrl;
    mfxEncodeCtrl *ctrlp = NULL;
    mfxSyncPoint syncp = NULL;
    mfxStatus sts;
    long long t0, t1, t2;
    int retries = 0;

    memset(frame, 0, sizeof(*frame));
    memset(&bs, 0, sizeof(bs));
    bs.Data = enc->bitstream_data;
    bs.MaxLength = (mfxU32)enc->bitstream_size;

    memset(&ctrl, 0, sizeof(ctrl));
    if (force_idr) {
        ctrl.FrameType = MFX_FRAMETYPE_I | MFX_FRAMETYPE_IDR | MFX_FRAMETYPE_REF;
        ctrlp = &ctrl;
    }
    /* Per-frame QP override is only honoured in CQP mode; in ICQ the driver
       silently ignores ctrl.QP. set_quality() refuses to populate next_qp
       when use_icq is set, so we don't need to re-check the mode here. */
    if (enc->next_qp > 0) {
        ctrl.QP = (mfxU16)enc->next_qp;
        ctrlp = &ctrl;
    }

    t0 = usec_now();
retry:
    sts = MFXVideoENCODE_EncodeFrameAsync(enc->session, ctrlp, surface, &bs, &syncp);
    t1 = usec_now();
    if (sts == MFX_WRN_DEVICE_BUSY) {
        if (retries++ < 100) {
            sleep_1ms();
            goto retry;
        }
        return set_error(enc, sts, "EncodeFrameAsync(device_busy)");
    }
    if (sts == MFX_ERR_MORE_DATA) {
        frame->us_submit = (int)(t1 - t0);
        return VPL_ENC_NEED_MORE_INPUT;
    }
    if (sts == MFX_ERR_NOT_ENOUGH_BUFFER) {
        return set_error(enc, sts, "EncodeFrameAsync(not_enough_buffer)");
    }
    /* Positive sts is a warning (e.g. MFX_WRN_INCOMPATIBLE_VIDEO_PARAM == 5):
       the frame was still accepted and a sync point produced, so output is
       available - fall through and sync it. A warning with no syncp is handled
       by the !syncp check below. Only negative codes are real errors.
       Never return here while a syncp is live, or the async worker keeps
       copying into enc->bitstream_data after we free it on teardown. */
    if (sts < MFX_ERR_NONE && sts != MFX_ERR_NONE_PARTIAL_OUTPUT) {
        return set_error(enc, sts, "EncodeFrameAsync");
    }
    if (!syncp) {
        frame->us_submit = (int)(t1 - t0);
        return VPL_ENC_NEED_MORE_INPUT;
    }

    enc->pending_sync = syncp;
    sts = MFXVideoCORE_SyncOperation(enc->session, syncp, 5000);
    t2 = usec_now();
    if (sts != MFX_ERR_NONE) {
        /* Leave pending_sync set: on timeout the frame may still be executing,
           so vpl_encoder_destroy() must drain it before freeing the buffers
           the async worker copies into. */
        return set_error(enc, sts, "SyncOperation");
    }
    enc->pending_sync = NULL;

    frame->data = bs.Data + bs.DataOffset;
    frame->size = (int)bs.DataLength;
    frame->frame_type = frame_type_from_mfx(bs.FrameType);
    frame->us_submit = (int)(t1 - t0);
    frame->us_sync = (int)(t2 - t1);
    return VPL_ENC_OK;
}

VPLEncodeStatus vpl_encoder_encode(VPLEncoder *enc,
                                   const uint8_t *y, int y_stride,
                                   const uint8_t *uv, int uv_stride,
                                   VPLEncodedFrame *frame) {
    long long t0, t1;

    if (!enc || !y || !uv || !frame)
        return VPL_ENC_ERROR;
    if (y_stride < enc->width || uv_stride < enc->width)
        return set_error(enc, MFX_ERR_INVALID_VIDEO_PARAM, "invalid NV12 stride");

    t0 = usec_now();
    copy_nv12(enc, y, y_stride, uv, uv_stride);
    t1 = usec_now();

    VPLEncodeStatus status = do_encode(enc, &enc->surface, enc->frames == 0, frame);
    frame->us_copy = (int)(t1 - t0);
    if (status == VPL_ENC_OK)
        enc->frames++;
    return status;
}

VPLEncodeStatus vpl_encoder_flush(VPLEncoder *enc, VPLEncodedFrame *frame) {
    if (!enc || !frame)
        return VPL_ENC_ERROR;
    return do_encode(enc, NULL, 0, frame);
}

/* Update the per-frame QP override from an xpra quality percentage (0..100).
   Only effective in CQP mode; in ICQ mode the call is a no-op and returns
   VPL_ENC_NOT_AVAILABLE so the caller can fall back to a Reset path later. */
VPLEncodeStatus vpl_encoder_set_quality(VPLEncoder *enc, int quality) {
    int q;
    if (!enc)
        return VPL_ENC_ERROR;
    enc->quality = clamp_int(quality, 0, 100);
    if (enc->use_icq)
        return VPL_ENC_NOT_AVAILABLE;
    q = 51 - (enc->quality * 50 + 50) / 100;
    enc->next_qp = clamp_int(q, 1, 51);
    return VPL_ENC_OK;
}

int vpl_encoder_is_hardware(VPLEncoder *enc) {
    return enc ? enc->is_hw : 0;
}

int vpl_encoder_get_width(VPLEncoder *enc) {
    return enc ? enc->width : 0;
}

int vpl_encoder_get_height(VPLEncoder *enc) {
    return enc ? enc->height : 0;
}

int vpl_encoder_get_last_status(VPLEncoder *enc) {
    return enc ? (int)enc->last_sts : 0;
}

const char* vpl_encoder_get_last_error(VPLEncoder *enc) {
    return enc ? enc->last_error : "no encoder";
}
