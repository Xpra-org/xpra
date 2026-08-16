/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: MediaFoundation video encoder - C implementation.
 * ABOUTME: Encodes YUV420P CPU buffers to H.264 or HEVC via IMFTransform. */

#include "mf_encode.h"

#define COBJMACROS
#include <windows.h>
#include <mfapi.h>
#include <mftransform.h>
#include <mfidl.h>
#include <mferror.h>
#include <codecapi.h>
#include <icodecapi.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>

#ifndef MF_LOW_LATENCY
DEFINE_GUID(MF_LOW_LATENCY, 0x9c27891a, 0xed7a, 0x40e1,
            0x88, 0xe8, 0xb2, 0x27, 0x27, 0xa0, 0x24, 0xee);
#endif

/* ICodecAPI is how an MFT exposes its tuning knobs, and each knob is named by a
   GUID. We take the values straight from the `STATIC_CODECAPI_*` macros in
   <codecapi.h> rather than linking the DirectShow GUID library just for these;
   the extra macro level is what lets the flat list of 11 numbers in those macros
   land in the braced initializer that `GUID` needs. */
#define MF_CODECAPI_GUID_(name, d1, d2, d3, b0, b1, b2, b3, b4, b5, b6, b7) \
    static const GUID MF_API_##name = {d1, d2, d3, {b0, b1, b2, b3, b4, b5, b6, b7}}
#define MF_CODECAPI_GUID(name, ...) MF_CODECAPI_GUID_(name, __VA_ARGS__)

MF_CODECAPI_GUID(AVEncCommonRateControlMode, STATIC_CODECAPI_AVEncCommonRateControlMode);
MF_CODECAPI_GUID(AVEncCommonQuality,         STATIC_CODECAPI_AVEncCommonQuality);
MF_CODECAPI_GUID(AVEncCommonQualityVsSpeed,  STATIC_CODECAPI_AVEncCommonQualityVsSpeed);
MF_CODECAPI_GUID(AVEncCommonMeanBitRate,     STATIC_CODECAPI_AVEncCommonMeanBitRate);
MF_CODECAPI_GUID(AVEncCommonMaxBitRate,      STATIC_CODECAPI_AVEncCommonMaxBitRate);
MF_CODECAPI_GUID(AVEncCommonLowLatency,      STATIC_CODECAPI_AVEncCommonLowLatency);
MF_CODECAPI_GUID(AVEncCommonRealTime,        STATIC_CODECAPI_AVEncCommonRealTime);
MF_CODECAPI_GUID(AVLowLatencyMode,           STATIC_CODECAPI_AVLowLatencyMode);
MF_CODECAPI_GUID(AVEncMPVGOPSize,            STATIC_CODECAPI_AVEncMPVGOPSize);
MF_CODECAPI_GUID(AVEncMPVDefaultBPictureCount, STATIC_CODECAPI_AVEncMPVDefaultBPictureCount);
MF_CODECAPI_GUID(AVEncVideoContentType,      STATIC_CODECAPI_AVEncVideoContentType);
MF_CODECAPI_GUID(AVEncAdaptiveMode,          STATIC_CODECAPI_AVEncAdaptiveMode);
MF_CODECAPI_GUID(AVEncH264CABACEnable,       STATIC_CODECAPI_AVEncH264CABACEnable);

/* IID_ICodecAPI, so we don't have to link `strmiids` for a single GUID */
static const GUID MF_IID_ICodecAPI =
    {0x901db4c7, 0x31ce, 0x41a2, {0x85, 0xdc, 0x8f, 0xa0, 0xbf, 0x41, 0xb8, 0xda}};

/* xpra sends frames when something changes rather than on a clock, so this is
   not a real frame rate - it is just the time base the encoder's rate control
   and GOP length are expressed in. The input samples are timestamped to match. */
#define MF_FPS 30
#define MF_FRAME_DURATION (10000000LL / MF_FPS)   /* one frame in 100-ns units */

/* Bitrate baseline at quality=50, in milli-bits per pixel per frame */
#define MF_MBPP_VIDEO   100   /* continuous tone: every bit goes somewhere useful */
#define MF_MBPP_SCREEN   60   /* mostly static, and what does change is flat colour */

#define MF_MIN_BITRATE      500000
#define MF_MAX_BITRATE    20000000
#define MF_MAX_PEAK_BITRATE 40000000

struct MFEncoder {
    IMFTransform   *transform;
    IMFMediaType   *input_type;
    IMFMediaType   *output_type;
    ICodecAPI      *codec_api;
    /* pre-allocated output sample for MFTs that don't provide their own */
    IMFSample      *out_sample;
    IMFMediaBuffer *out_mbuf;
    int             provides_samples;
    int             codec;
    int             width;
    int             height;
    MFEncoderTuning tuning;
    MFTuningInfo    applied;
    DWORD           mean_bitrate;
    DWORD           max_bitrate;
    /* NV12 scratch buffer for YUV420P → NV12 conversion */
    int             nv12_stride;
    uint8_t        *nv12_buf;
    int             nv12_buf_size;
    /* encoded bitstream copy owned by us */
    uint8_t        *encoded_buf;
    int             encoded_buf_size;
    long long       frame_count;
    HRESULT         last_hr;
    char            last_error[128];
};

static int       g_enc_com_owned = 0;
static int       g_enc_mf_started = 0;
static mf_log_fn g_enc_log_fn = NULL;

/* ── logging ─────────────────────────────────────────────────────── */

void mf_encode_set_log(mf_log_fn fn) {
    g_enc_log_fn = fn;
}

static void enc_log(const char *fmt, ...) {
    if (!g_enc_log_fn) return;
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    g_enc_log_fn(buf);
}

static MFEncodeStatus set_enc_error(MFEncoder *enc, HRESULT hr, const char *context) {
    if (enc) {
        enc->last_hr = hr;
        snprintf(enc->last_error, sizeof(enc->last_error),
                 "%s failed: HRESULT 0x%08lX", context, (unsigned long)hr);
        enc_log("mf encoder: %s", enc->last_error);
    }
    return MF_ENC_ERROR;
}

static LARGE_INTEGER g_enc_perf_freq = {0};

static long long enc_usec_now(void) {
    LARGE_INTEGER now;
    if (g_enc_perf_freq.QuadPart == 0)
        QueryPerformanceFrequency(&g_enc_perf_freq);
    QueryPerformanceCounter(&now);
    return (long long)(now.QuadPart * 1000000 / g_enc_perf_freq.QuadPart);
}

/* ── global lifecycle ────────────────────────────────────────────── */

MFEncodeStatus mf_encode_startup(void) {
    HRESULT hr;
    enc_log("mf_encode_startup: initializing COM");
    hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    if (hr == RPC_E_CHANGED_MODE) {
        enc_log("mf_encode_startup: COM already initialized (STA), reusing");
        g_enc_com_owned = 0;
    } else if (FAILED(hr)) {
        enc_log("mf_encode_startup: CoInitializeEx failed: 0x%08lX", (unsigned long)hr);
        return MF_ENC_ERROR;
    } else {
        g_enc_com_owned = 1;
    }

    hr = MFStartup(MF_VERSION, MFSTARTUP_LITE);
    if (FAILED(hr)) {
        enc_log("mf_encode_startup: MFStartup failed: 0x%08lX", (unsigned long)hr);
        if (g_enc_com_owned) CoUninitialize();
        g_enc_com_owned = 0;
        return MF_ENC_ERROR;
    }

    enc_log("mf_encode_startup: MediaFoundation started");
    g_enc_mf_started = 1;
    return MF_ENC_OK;
}

void mf_encode_shutdown(void) {
    if (g_enc_mf_started) {
        MFShutdown();
        g_enc_mf_started = 0;
    }
    if (g_enc_com_owned) {
        CoUninitialize();
        g_enc_com_owned = 0;
    }
}

/* ── codec helpers ───────────────────────────────────────────────── */

static const GUID* enc_codec_to_subtype(int codec) {
    switch (codec) {
        case MF_CODEC_H264: return &MFVideoFormat_H264;
        case MF_CODEC_HEVC: return &MFVideoFormat_HEVC;
        default:            return NULL;
    }
}

static const char* enc_codec_to_name(int codec) {
    switch (codec) {
        case MF_CODEC_H264: return "H.264";
        case MF_CODEC_HEVC: return "HEVC";
        default:            return "unknown";
    }
}

/* ── tuning ──────────────────────────────────────────────────────── */

const char* mf_rate_control_str(int rate_control) {
    switch (rate_control) {
        case eAVEncCommonRateControlMode_CBR:                  return "CBR";
        case eAVEncCommonRateControlMode_PeakConstrainedVBR:   return "peak constrained VBR";
        case eAVEncCommonRateControlMode_UnconstrainedVBR:     return "unconstrained VBR";
        case eAVEncCommonRateControlMode_Quality:              return "quality";
        case eAVEncCommonRateControlMode_LowDelayVBR:          return "low delay VBR";
        case eAVEncCommonRateControlMode_GlobalVBR:            return "global VBR";
        case eAVEncCommonRateControlMode_GlobalLowDelayVBR:    return "global low delay VBR";
        default:                                               return "";
    }
}

static const char* content_type_str(int content_type) {
    switch (content_type) {
        case MF_CONTENT_SCREEN: return "screen";
        case MF_CONTENT_VIDEO:  return "video";
        default:                return "unknown";
    }
}

static int clamp_pct(int value, int fallback) {
    if (value < 0)   return fallback;
    if (value > 100) return 100;
    return value;
}

/* everything that isn't positively identified as continuous tone is screen content */
static int is_video_content(const MFEncoderTuning *t) {
    return t->content_type == MF_CONTENT_VIDEO;
}

static void reset_tuning_info(MFTuningInfo *info) {
    info->codec_api        = 0;
    info->rate_control     = -1;
    info->mean_bitrate     = -1;
    info->max_bitrate      = -1;
    info->quality          = -1;
    info->quality_vs_speed = -1;
    info->gop_size         = -1;
    info->bframes          = -1;
    info->low_latency      = -1;
    info->content_type     = -1;
    info->adaptive_mode    = -1;
    info->cabac            = -1;
    info->profile          = -1;
}

/* `IsSupported` and `IsModifiable` both answer "no" with S_FALSE, which is a
   *success* code - so these have to test for S_OK rather than use SUCCEEDED() */
static int codecapi_supported(MFEncoder *enc, const GUID *api) {
    return enc->codec_api && ICodecAPI_IsSupported(enc->codec_api, api) == S_OK;
}

static int codecapi_modifiable(MFEncoder *enc, const GUID *api) {
    return enc->codec_api && ICodecAPI_IsModifiable(enc->codec_api, api) == S_OK;
}

static int codecapi_set(MFEncoder *enc, const GUID *api, VARIANT *value,
                        const char *name, long lvalue) {
    HRESULT hr;
    if (!codecapi_supported(enc, api)) {
        enc_log("mf tuning: %s is not supported", name);
        return 0;
    }
    hr = ICodecAPI_SetValue(enc->codec_api, api, value);
    if (FAILED(hr)) {
        enc_log("mf tuning: %s=%ld rejected: 0x%08lX", name, lvalue, (unsigned long)hr);
        return 0;
    }
    enc_log("mf tuning: %s=%ld", name, lvalue);
    return 1;
}

static int codecapi_set_u32(MFEncoder *enc, const GUID *api, UINT32 value, const char *name) {
    VARIANT v;
    memset(&v, 0, sizeof(v));
    V_VT(&v)  = VT_UI4;
    V_UI4(&v) = value;
    return codecapi_set(enc, api, &v, name, (long)value);
}

static int codecapi_set_bool(MFEncoder *enc, const GUID *api, int value, const char *name) {
    VARIANT v;
    memset(&v, 0, sizeof(v));
    V_VT(&v)   = VT_BOOL;
    V_BOOL(&v) = value ? VARIANT_TRUE : VARIANT_FALSE;
    return codecapi_set(enc, api, &v, name, (long)value);
}

/* how many bits per second this window is worth */
static void compute_bitrates(MFEncoder *enc) {
    const MFEncoderTuning *t = &enc->tuning;
    int quality = clamp_pct(t->quality, 50);
    unsigned long long pixel_rate = (unsigned long long)enc->width * enc->height * MF_FPS;
    unsigned long long mean = pixel_rate * (is_video_content(t) ? MF_MBPP_VIDEO : MF_MBPP_SCREEN) / 1000;
    unsigned long long peak;

    /* quality moves the baseline between half and one and a half times: */
    mean = mean * (50 + quality) / 100;
    if (mean < MF_MIN_BITRATE) mean = MF_MIN_BITRATE;
    if (mean > MF_MAX_BITRATE) mean = MF_MAX_BITRATE;

    /* screen content is bursty - near zero while nothing moves, then a full
       redraw - so it needs far more headroom above its mean than video does: */
    peak = is_video_content(t) ? mean * 3 / 2 : mean * 3;
    if (peak > MF_MAX_PEAK_BITRATE) peak = MF_MAX_PEAK_BITRATE;

    /* a bandwidth limit is a hard ceiling: it applies to the peak, not the average */
    if (t->bandwidth_limit > 0) {
        if (peak > (unsigned long long)t->bandwidth_limit) peak = (unsigned long long)t->bandwidth_limit;
        if (mean > peak) mean = peak;
    }

    enc->mean_bitrate = (DWORD)mean;
    enc->max_bitrate  = (DWORD)peak;
}

/* pick the rate control mode - the first one this MFT accepts wins */
static void apply_rate_control(MFEncoder *enc) {
    /* screen content is what we would like to encode at a constant *quality*:
       a still desktop should cost nothing at all, and the text that does get
       redrawn should stay sharp instead of being smeared to hit an average. */
    static const UINT32 by_quality[] = {
        eAVEncCommonRateControlMode_Quality,
        eAVEncCommonRateControlMode_UnconstrainedVBR,
        eAVEncCommonRateControlMode_PeakConstrainedVBR,
        eAVEncCommonRateControlMode_CBR,
    };
    /* video is a continuous stream that will happily eat everything it is given,
       and a bandwidth limit is a promise we have to keep, so both are capped: */
    static const UINT32 by_bitrate[] = {
        eAVEncCommonRateControlMode_PeakConstrainedVBR,
        eAVEncCommonRateControlMode_UnconstrainedVBR,
        eAVEncCommonRateControlMode_CBR,
    };
    const UINT32 *modes;
    size_t count, i;

    if (is_video_content(&enc->tuning) || enc->tuning.bandwidth_limit > 0) {
        modes = by_bitrate;
        count = sizeof(by_bitrate) / sizeof(by_bitrate[0]);
    } else {
        modes = by_quality;
        count = sizeof(by_quality) / sizeof(by_quality[0]);
    }
    for (i = 0; i < count; i++) {
        if (codecapi_set_u32(enc, &MF_API_AVEncCommonRateControlMode, modes[i], "rate-control")) {
            enc->applied.rate_control = (int)modes[i];
            return;
        }
    }
}

/* Ask for everything the tuning implies. Knobs that were already applied are
   skipped, so this can safely be called twice: some MFTs refuse ICodecAPI values
   until they know the format, others stop accepting them once they do. */
static void apply_static_tuning(MFEncoder *enc) {
    const MFEncoderTuning *t = &enc->tuning;
    MFTuningInfo *info = &enc->applied;
    const int video = is_video_content(t);
    int quality = clamp_pct(t->quality, 50);
    int speed   = clamp_pct(t->speed, 50);
    int gop;

    if (!enc->codec_api)
        return;

    /* first, because it decides whether the quality or the bitrate knobs
       are the ones that mean anything: */
    if (info->rate_control < 0)
        apply_rate_control(enc);

    if (info->rate_control == eAVEncCommonRateControlMode_Quality) {
        /* MF's quality scale is unusable at the bottom, so keep it off the floor: */
        UINT32 mf_quality = (UINT32)(15 + quality * 85 / 100);
        if (info->quality < 0 && codecapi_set_u32(enc, &MF_API_AVEncCommonQuality, mf_quality, "quality"))
            info->quality = (int)mf_quality;
    } else {
        if (info->mean_bitrate < 0 &&
            codecapi_set_u32(enc, &MF_API_AVEncCommonMeanBitRate, enc->mean_bitrate, "mean-bitrate"))
            info->mean_bitrate = (int)enc->mean_bitrate;
        if (info->max_bitrate < 0 &&
            codecapi_set_u32(enc, &MF_API_AVEncCommonMaxBitRate, enc->max_bitrate, "max-bitrate"))
            info->max_bitrate = (int)enc->max_bitrate;
    }

    /* the one knob that is exactly what xpra's `speed` means, just the other way
       round: 0 asks the encoder for speed, 100 asks it for compression */
    if (info->quality_vs_speed < 0 &&
        codecapi_set_u32(enc, &MF_API_AVEncCommonQualityVsSpeed, (UINT32)(100 - speed), "quality-vs-speed"))
        info->quality_vs_speed = 100 - speed;

    /* a remote display is interactive even when it is showing a film: never let
       the encoder buffer frames to compress them better */
    if (info->low_latency < 0) {
        int ll = 0;
        ll |= codecapi_set_bool(enc, &MF_API_AVLowLatencyMode, 1, "low-latency-mode");
        ll |= codecapi_set_bool(enc, &MF_API_AVEncCommonLowLatency, 1, "low-latency");
        ll |= codecapi_set_bool(enc, &MF_API_AVEncCommonRealTime, 1, "real-time");
        if (ll)
            info->low_latency = 1;
    }

    /* xpra never seeks, and asks for a refresh when it needs one, so keyframes
       are pure overhead - but a periodic one still bounds the damage a lost or
       corrupt frame can do. An intra frame costs most on screen content (a full
       screen of text, usually while nothing is even moving), so that is where
       the GOP gets stretched furthest: */
    gop = video ? MF_FPS * 10 : MF_FPS * 60;
    if (info->gop_size < 0 && codecapi_set_u32(enc, &MF_API_AVEncMPVGOPSize, (UINT32)gop, "gop-size"))
        info->gop_size = gop;

    /* every B picture is another frame of latency before anything can be sent */
    if (info->bframes < 0 && codecapi_set_u32(enc, &MF_API_AVEncMPVDefaultBPictureCount, 0, "b-frames"))
        info->bframes = 0;

    /* `FixedCameraAngle` tells the encoder the background does not move, which is
       what makes a desktop cheap to encode: it is the extreme case of a static
       camera. Real video pans and cuts, so it gets no such promise: */
    if (info->content_type < 0) {
        UINT32 mf_content = video ? eAVEncVideoContentType_Unknown : eAVEncVideoContentType_FixedCameraAngle;
        if (codecapi_set_u32(enc, &MF_API_AVEncVideoContentType, mf_content, "content-type"))
            info->content_type = (int)mf_content;
    }

    /* frames arrive when the window changes, not on a clock, so let the rate
       control cope with a variable frame rate - except for video, which really
       does arrive at a steady rate and whose rate control is better off assuming it: */
    if (info->adaptive_mode < 0) {
        UINT32 mode = video ? eAVEncAdaptiveMode_None : eAVEncAdaptiveMode_FrameRate;
        if (codecapi_set_u32(enc, &MF_API_AVEncAdaptiveMode, mode, "adaptive-mode"))
            info->adaptive_mode = (int)mode;
    }

    /* CABAC buys around 10% fewer bits for a slower encode and a slower decode,
       which is a bad trade exactly when the pipeline is asking for speed: */
    if (enc->codec == MF_CODEC_H264 && info->cabac < 0) {
        int cabac = speed < 80;
        if (codecapi_set_bool(enc, &MF_API_AVEncH264CABACEnable, cabac, "cabac"))
            info->cabac = cabac;
    }
}

/* the profile is part of the output media type rather than an ICodecAPI knob */
static UINT32 get_profile(int codec, int speed) {
    if (codec == MF_CODEC_HEVC)
        return eAVEncH265VProfile_Main_420_8;
    /* `High` is worth about 10% over `Main` (8x8 transform, better intra
       prediction) for a little more work, so give it up only when the pipeline
       is asking for speed. xpra's other h264 encoders default to `high` for
       YUV420P, so every decoder we talk to can already handle it: */
    return (speed >= 80) ? eAVEncH264VProfile_Main : eAVEncH264VProfile_High;
}

/* ── YUV420P → NV12 conversion ───────────────────────────────────── */

/* The row pitch we stage frames at. Hardware encoders want their input aligned, and
   16 bytes suits every MFT we have seen - but whatever we pick has to be declared on
   the input media type, see `input_stride`. */
#define MF_NV12_STRIDE(width) (((width) + 15) & ~15)

/* NV12 layout: Y plane (stride * height rows) immediately followed by
   interleaved UV plane (stride * height/2 rows, U byte then V byte). */
static void yuv420p_to_nv12(uint8_t *dst, int dst_stride,
                              const uint8_t *y, int y_stride,
                              const uint8_t *u, int u_stride,
                              const uint8_t *v, int v_stride,
                              int width, int height) {
    int row, col;
    uint8_t *dst_y  = dst;
    uint8_t *dst_uv = dst + (size_t)dst_stride * height;
    int uv_width  = (width  + 1) / 2;
    int uv_height = (height + 1) / 2;

    for (row = 0; row < height; row++)
        memcpy(dst_y + (size_t)row * dst_stride, y + (size_t)row * y_stride, (size_t)width);

    for (row = 0; row < uv_height; row++) {
        const uint8_t *ur = u + (size_t)row * u_stride;
        const uint8_t *vr = v + (size_t)row * v_stride;
        uint8_t       *dr = dst_uv + (size_t)row * dst_stride;
        for (col = 0; col < uv_width; col++) {
            dr[2 * col]     = ur[col];
            dr[2 * col + 1] = vr[col];
        }
    }
}

/* ── encoder creation ────────────────────────────────────────────── */

/* The pitch the MFT will read our input buffer at. It should be the one we asked for
   on the media type, but an MFT is free to hand back a type of its own, so ask what
   it ended up with instead of assuming. Falls back to the width, which is what
   MediaFoundation assumes for NV12 when the type carries no stride at all. */
static int input_stride(MFEncoder *enc, int width) {
    IMFMediaType *current = NULL;
    UINT32 stride = 0;
    HRESULT hr = E_FAIL;

    if (SUCCEEDED(IMFTransform_GetInputCurrentType(enc->transform, 0, &current)) && current) {
        hr = IMFMediaType_GetUINT32(current, &MF_MT_DEFAULT_STRIDE, &stride);
        IMFMediaType_Release(current);
    }
    if (FAILED(hr) && enc->input_type)
        hr = IMFMediaType_GetUINT32(enc->input_type, &MF_MT_DEFAULT_STRIDE, &stride);
    if (SUCCEEDED(hr) && (INT32)stride >= width)
        return (int)stride;
    enc_log("mf_encoder_create: MFT kept no input stride, staging rows %d bytes apart", width);
    return width;
}

MFEncodeStatus mf_encoder_create(MFEncoder **out, int codec, int width, int height,
                                 const MFEncoderTuning *tuning) {
    HRESULT hr;
    MFEncoder *enc;
    IMFActivate **activates = NULL;
    UINT32 num_activates = 0;
    MFT_REGISTER_TYPE_INFO output_info;
    DWORD i;
    const GUID *out_subtype;
    UINT32 profile;

    *out = NULL;

    out_subtype = enc_codec_to_subtype(codec);
    if (!out_subtype)
        return MF_ENC_NOT_AVAILABLE;

    enc = (MFEncoder *)calloc(1, sizeof(MFEncoder));
    if (!enc)
        return MF_ENC_ERROR;

    enc->codec  = codec;
    enc->width  = width;
    enc->height = height;
    if (tuning) {
        enc->tuning = *tuning;
    } else {
        enc->tuning.content_type    = MF_CONTENT_UNKNOWN;
        enc->tuning.quality         = 50;
        enc->tuning.speed           = 50;
        enc->tuning.bandwidth_limit = 0;
    }
    reset_tuning_info(&enc->applied);

    /* enumerate encoders that produce the requested compressed format */
    output_info.guidMajorType = MFMediaType_Video;
    output_info.guidSubtype   = *out_subtype;

    enc_log("mf_encoder_create: enumerating %s encoders for %dx%d",
            enc_codec_to_name(codec), width, height);
    hr = MFTEnumEx(MFT_CATEGORY_VIDEO_ENCODER,
                   MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_HARDWARE | MFT_ENUM_FLAG_SORTANDFILTER,
                   NULL, &output_info, &activates, &num_activates);
    enc_log("mf_encoder_create: MFTEnumEx hr=0x%08lX num=%u",
            (unsigned long)hr, (unsigned int)num_activates);

    if (FAILED(hr) || num_activates == 0) {
        if (activates) CoTaskMemFree(activates);
        free(enc);
        return MF_ENC_NOT_AVAILABLE;
    }

    hr = IMFActivate_ActivateObject(activates[0], &IID_IMFTransform, (void **)&enc->transform);
    for (i = 0; i < num_activates; i++)
        IMFActivate_Release(activates[i]);
    CoTaskMemFree(activates);

    if (FAILED(hr)) {
        enc_log("mf_encoder_create: ActivateObject failed: 0x%08lX", (unsigned long)hr);
        free(enc);
        return MF_ENC_ERROR;
    }
    enc_log("mf_encoder_create: MFT activated");

    /* enable low-latency mode via MFT attributes (best-effort) */
    {
        IMFAttributes *attrs = NULL;
        if (SUCCEEDED(IMFTransform_GetAttributes(enc->transform, &attrs)) && attrs) {
            IMFAttributes_SetUINT32(attrs, &MF_LOW_LATENCY, TRUE);
            IMFAttributes_Release(attrs);
        }
    }

    /* the tuning knobs live behind ICodecAPI, which not every MFT exposes */
    hr = IMFTransform_QueryInterface(enc->transform, &MF_IID_ICodecAPI, (void **)&enc->codec_api);
    if (FAILED(hr) || !enc->codec_api) {
        enc->codec_api = NULL;
        enc_log("mf_encoder_create: no ICodecAPI (0x%08lX), using the MFT defaults", (unsigned long)hr);
    }
    enc->applied.codec_api = enc->codec_api != NULL;

    compute_bitrates(enc);
    enc_log("mf_encoder_create: %s content, quality=%d speed=%d, bitrate=%lu/%lu bps",
            content_type_str(enc->tuning.content_type), enc->tuning.quality, enc->tuning.speed,
            (unsigned long)enc->mean_bitrate, (unsigned long)enc->max_bitrate);

    /* most MFTs want their ICodecAPI parameters before the media types */
    apply_static_tuning(enc);

    /* set output type (compressed format) — must precede input type for encoders */
    hr = MFCreateMediaType(&enc->output_type);
    if (FAILED(hr)) { set_enc_error(enc, hr, "MFCreateMediaType(output)"); goto fail; }

    profile = get_profile(codec, clamp_pct(enc->tuning.speed, 50));
    IMFMediaType_SetGUID(enc->output_type,   &MF_MT_MAJOR_TYPE,        &MFMediaType_Video);
    IMFMediaType_SetGUID(enc->output_type,   &MF_MT_SUBTYPE,           out_subtype);
    IMFMediaType_SetUINT64(enc->output_type, &MF_MT_FRAME_SIZE,        ((UINT64)width << 32) | (UINT64)height);
    IMFMediaType_SetUINT32(enc->output_type, &MF_MT_INTERLACE_MODE,    MFVideoInterlace_Progressive);
    IMFMediaType_SetUINT64(enc->output_type, &MF_MT_FRAME_RATE,        ((UINT64)MF_FPS << 32) | 1ULL);
    IMFMediaType_SetUINT64(enc->output_type, &MF_MT_PIXEL_ASPECT_RATIO,((UINT64)1  << 32) | 1ULL);
    IMFMediaType_SetUINT32(enc->output_type, &MF_MT_AVG_BITRATE,       enc->mean_bitrate);
    IMFMediaType_SetUINT32(enc->output_type, &MF_MT_MPEG2_PROFILE,     profile);
    enc->applied.profile = (int)profile;

    hr = IMFTransform_SetOutputType(enc->transform, 0, enc->output_type, 0);
    if (FAILED(hr)) {
        /* an MFT that doesn't support the profile we asked for rejects the whole
           output type, so drop it and let the encoder pick its own: */
        enc_log("mf_encoder_create: SetOutputType(%s, profile=%lu) failed: 0x%08lX, retrying without a profile",
                enc_codec_to_name(codec), (unsigned long)profile, (unsigned long)hr);
        IMFMediaType_DeleteItem(enc->output_type, &MF_MT_MPEG2_PROFILE);
        enc->applied.profile = -1;
        hr = IMFTransform_SetOutputType(enc->transform, 0, enc->output_type, 0);
    }
    if (FAILED(hr)) {
        enc_log("mf_encoder_create: SetOutputType(%s) failed: 0x%08lX",
                enc_codec_to_name(codec), (unsigned long)hr);
        goto fail;
    }
    enc_log("mf_encoder_create: output type set (%s, %dx%d, %lubps, profile=%d)",
            enc_codec_to_name(codec), width, height,
            (unsigned long)enc->mean_bitrate, enc->applied.profile);

    /* enumerate input types offered by the MFT, select NV12 */
    {
        int found = 0;
        for (i = 0; ; i++) {
            IMFMediaType *candidate = NULL;
            GUID in_subtype = {0};
            hr = IMFTransform_GetInputAvailableType(enc->transform, 0, i, &candidate);
            if (FAILED(hr)) break;

            IMFMediaType_GetGUID(candidate, &MF_MT_SUBTYPE, &in_subtype);
            enc_log("mf_encoder_create: input type %lu: {%08lX-...}",
                    (unsigned long)i, (unsigned long)in_subtype.Data1);

            if (IsEqualGUID(&in_subtype, &MFVideoFormat_NV12)) {
                IMFMediaType_SetGUID(candidate,   &MF_MT_MAJOR_TYPE,        &MFMediaType_Video);
                IMFMediaType_SetGUID(candidate,   &MF_MT_SUBTYPE,           &MFVideoFormat_NV12);
                IMFMediaType_SetUINT64(candidate, &MF_MT_FRAME_SIZE,        ((UINT64)width << 32) | (UINT64)height);
                IMFMediaType_SetUINT32(candidate, &MF_MT_INTERLACE_MODE,    MFVideoInterlace_Progressive);
                IMFMediaType_SetUINT64(candidate, &MF_MT_FRAME_RATE,        ((UINT64)MF_FPS << 32) | 1ULL);
                /* Tell the MFT the pitch we are going to hand it. Left to itself it
                   assumes the rows of an NV12 buffer are exactly `width` bytes apart,
                   so it would read our aligned staging buffer at a steadily growing
                   offset and skew the picture diagonally - for every width that is not
                   already a multiple of 16. */
                IMFMediaType_SetUINT32(candidate, &MF_MT_DEFAULT_STRIDE,    (UINT32)MF_NV12_STRIDE(width));

                hr = IMFTransform_SetInputType(enc->transform, 0, candidate, 0);
                enc->input_type = candidate; /* take ownership */
                if (FAILED(hr)) {
                    enc_log("mf_encoder_create: SetInputType(NV12) failed: 0x%08lX", (unsigned long)hr);
                    goto fail;
                }
                found = 1;
                enc_log("mf_encoder_create: NV12 input type set");
                break;
            }
            IMFMediaType_Release(candidate);
        }
        if (!found) {
            enc_log("mf_encoder_create: NV12 input not available for %s", enc_codec_to_name(codec));
            goto fail;
        }
    }

    /* retry whatever was refused before the formats were known: some MFTs only
       accept their ICodecAPI parameters once both media types are set */
    apply_static_tuning(enc);

    /* check whether the MFT allocates its own output samples */
    {
        MFT_OUTPUT_STREAM_INFO sinfo;
        memset(&sinfo, 0, sizeof(sinfo));
        hr = IMFTransform_GetOutputStreamInfo(enc->transform, 0, &sinfo);
        if (SUCCEEDED(hr)) {
            enc->provides_samples = (sinfo.dwFlags &
                (MFT_OUTPUT_STREAM_PROVIDES_SAMPLES | MFT_OUTPUT_STREAM_LAZY_READ)) ? 1 : 0;
            enc_log("mf_encoder_create: provides_samples=%d cbSize=%lu dwFlags=0x%lX",
                    enc->provides_samples, (unsigned long)sinfo.cbSize, (unsigned long)sinfo.dwFlags);

            if (!enc->provides_samples) {
                /* pre-allocate a reusable output sample; size is generous (full uncompressed frame) */
                DWORD buf_size = sinfo.cbSize;
                if (buf_size == 0) buf_size = (DWORD)((size_t)width * height * 3 / 2);

                hr = MFCreateMemoryBuffer(buf_size, &enc->out_mbuf);
                if (FAILED(hr)) { set_enc_error(enc, hr, "MFCreateMemoryBuffer(output)"); goto fail; }
                hr = MFCreateSample(&enc->out_sample);
                if (FAILED(hr)) { set_enc_error(enc, hr, "MFCreateSample(output)"); goto fail; }
                IMFSample_AddBuffer(enc->out_sample, enc->out_mbuf);
            }
        }
    }

    /* begin streaming */
    IMFTransform_ProcessMessage(enc->transform, MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
    IMFTransform_ProcessMessage(enc->transform, MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);

    /* allocate the NV12 scratch buffer at the pitch the MFT reads it back at */
    enc->nv12_stride   = input_stride(enc, width);
    enc->nv12_buf_size = enc->nv12_stride * height * 3 / 2;
    enc->nv12_buf      = (uint8_t *)malloc((size_t)enc->nv12_buf_size);
    if (!enc->nv12_buf) {
        enc_log("mf_encoder_create: malloc nv12_buf failed");
        goto fail;
    }

    enc_log("mf_encoder_create: encoder ready (%dx%d nv12_stride=%d provides_samples=%d)",
            width, height, enc->nv12_stride, enc->provides_samples);
    enc_log("mf_encoder_create: rate-control=%s quality=%d quality-vs-speed=%d gop=%d",
            mf_rate_control_str(enc->applied.rate_control), enc->applied.quality,
            enc->applied.quality_vs_speed, enc->applied.gop_size);
    *out = enc;
    return MF_ENC_OK;

fail:
    mf_encoder_destroy(enc);
    return MF_ENC_NOT_AVAILABLE;
}

/* ── encoding ────────────────────────────────────────────────────── */

static MFEncodeStatus try_get_encoded(MFEncoder *enc, MFEncodedFrame *frame) {
    HRESULT hr;
    MFT_OUTPUT_DATA_BUFFER out_buf;
    DWORD status_flags = 0;
    IMFSample      *result_sample = NULL;
    IMFMediaBuffer *out_mbuf      = NULL;
    BYTE           *data          = NULL;
    DWORD           cur_len       = 0;
    UINT32          clean_point   = 0;

    memset(&out_buf, 0, sizeof(out_buf));
    out_buf.dwStreamID = 0;

    if (!enc->provides_samples) {
        /* reset buffer length so the MFT sees an empty buffer to write into */
        if (enc->out_mbuf)
            IMFMediaBuffer_SetCurrentLength(enc->out_mbuf, 0);
        out_buf.pSample = enc->out_sample;
    }
    /* if provides_samples: leave pSample = NULL, MFT sets it */

    hr = IMFTransform_ProcessOutput(enc->transform, 0, 1, &out_buf, &status_flags);

    if (hr == MF_E_TRANSFORM_NEED_MORE_INPUT) {
        frame->data     = NULL;
        frame->data_len = 0;
        return MF_ENC_NEED_MORE_INPUT;
    }
    if (FAILED(hr))
        return set_enc_error(enc, hr, "ProcessOutput");

    result_sample = out_buf.pSample;
    if (!result_sample) {
        frame->data     = NULL;
        frame->data_len = 0;
        return MF_ENC_NEED_MORE_INPUT;
    }

    IMFSample_GetUINT32(result_sample, &MFSampleExtension_CleanPoint, &clean_point);

    hr = IMFSample_ConvertToContiguousBuffer(result_sample, &out_mbuf);
    /* release MFT-provided sample now that we have the buffer reference */
    if (enc->provides_samples)
        IMFSample_Release(result_sample);
    if (FAILED(hr))
        return set_enc_error(enc, hr, "ConvertToContiguousBuffer");

    hr = IMFMediaBuffer_Lock(out_mbuf, &data, NULL, &cur_len);
    if (FAILED(hr)) {
        IMFMediaBuffer_Release(out_mbuf);
        return set_enc_error(enc, hr, "IMFMediaBuffer_Lock(output)");
    }

    /* grow our copy buffer if necessary */
    if ((int)cur_len > enc->encoded_buf_size) {
        uint8_t *nb = (uint8_t *)realloc(enc->encoded_buf, (size_t)cur_len);
        if (!nb) {
            IMFMediaBuffer_Unlock(out_mbuf);
            IMFMediaBuffer_Release(out_mbuf);
            return set_enc_error(enc, E_OUTOFMEMORY, "realloc encoded_buf");
        }
        enc->encoded_buf      = nb;
        enc->encoded_buf_size = (int)cur_len;
    }

    memcpy(enc->encoded_buf, data, (size_t)cur_len);
    IMFMediaBuffer_Unlock(out_mbuf);
    IMFMediaBuffer_Release(out_mbuf);

    frame->data        = enc->encoded_buf;
    frame->data_len    = (int)cur_len;
    frame->is_keyframe = clean_point ? 1 : 0;
    enc_log("mf encode: %d bytes keyframe=%d", (int)cur_len, frame->is_keyframe);
    return MF_ENC_OK;
}

/* ── shared inner encode — NV12 buffer already in enc->nv12_buf ──── */

static MFEncodeStatus do_encode_nv12(MFEncoder *enc, MFEncodedFrame *frame) {
    HRESULT hr;
    IMFSample      *in_sample = NULL;
    IMFMediaBuffer *in_mbuf   = NULL;
    BYTE           *buf_ptr   = NULL;
    long long       t0, t1, t2;

    /* wrap the pre-converted NV12 scratch buffer in an MF sample */
    t0 = enc_usec_now();
    hr = MFCreateMemoryBuffer((DWORD)enc->nv12_buf_size, &in_mbuf);
    if (FAILED(hr)) return set_enc_error(enc, hr, "MFCreateMemoryBuffer(input)");

    hr = IMFMediaBuffer_Lock(in_mbuf, &buf_ptr, NULL, NULL);
    if (FAILED(hr)) { IMFMediaBuffer_Release(in_mbuf); return set_enc_error(enc, hr, "Lock(input)"); }
    memcpy(buf_ptr, enc->nv12_buf, (size_t)enc->nv12_buf_size);
    IMFMediaBuffer_Unlock(in_mbuf);
    IMFMediaBuffer_SetCurrentLength(in_mbuf, (DWORD)enc->nv12_buf_size);

    hr = MFCreateSample(&in_sample);
    if (FAILED(hr)) { IMFMediaBuffer_Release(in_mbuf); return set_enc_error(enc, hr, "MFCreateSample(input)"); }
    IMFSample_AddBuffer(in_sample, in_mbuf);
    IMFMediaBuffer_Release(in_mbuf);

    /* timestamps on the same time base as the media types, in 100-ns units */
    IMFSample_SetSampleTime(in_sample,     enc->frame_count * MF_FRAME_DURATION);
    IMFSample_SetSampleDuration(in_sample, MF_FRAME_DURATION);

    hr = IMFTransform_ProcessInput(enc->transform, 0, in_sample, 0);
    t1 = enc_usec_now();
    IMFSample_Release(in_sample);

    if (FAILED(hr) && hr != MF_E_NOTACCEPTING)
        return set_enc_error(enc, hr, "ProcessInput");

    enc->frame_count++;

    MFEncodeStatus st = try_get_encoded(enc, frame);
    t2 = enc_usec_now();
    frame->us_input  = (int)(t1 - t0);
    frame->us_output = (int)(t2 - t1);
    return st;
}

/* ── runtime tuning ──────────────────────────────────────────────── */

/* only worth attempting on a knob the MFT said it would accept while running */
static int codecapi_update_u32(MFEncoder *enc, const GUID *api, UINT32 value, const char *name) {
    if (!codecapi_modifiable(enc, api)) {
        enc_log("mf tuning: %s cannot be changed on a running encoder", name);
        return 0;
    }
    return codecapi_set_u32(enc, api, value, name);
}

MFEncodeStatus mf_encoder_set_tuning(MFEncoder *enc, const MFEncoderTuning *tuning) {
    MFTuningInfo *info;
    int quality, speed;
    int changed = 0;

    if (!enc || !tuning)
        return MF_ENC_ERROR;

    /* the content type is not updated here: it picks the rate control mode, the
       GOP length and the encoder's content hint, none of which an open MFT will
       take back - the caller creates a new encoder when it changes */
    enc->tuning.quality         = tuning->quality;
    enc->tuning.speed           = tuning->speed;
    enc->tuning.bandwidth_limit = tuning->bandwidth_limit;
    compute_bitrates(enc);

    if (!enc->codec_api)
        return MF_ENC_NOT_AVAILABLE;

    info    = &enc->applied;
    quality = clamp_pct(enc->tuning.quality, 50);
    speed   = clamp_pct(enc->tuning.speed, 50);

    if (info->rate_control == eAVEncCommonRateControlMode_Quality) {
        UINT32 mf_quality = (UINT32)(15 + quality * 85 / 100);
        if (info->quality != (int)mf_quality &&
            codecapi_update_u32(enc, &MF_API_AVEncCommonQuality, mf_quality, "quality")) {
            info->quality = (int)mf_quality;
            changed = 1;
        }
    } else {
        if (info->mean_bitrate != (int)enc->mean_bitrate &&
            codecapi_update_u32(enc, &MF_API_AVEncCommonMeanBitRate, enc->mean_bitrate, "mean-bitrate")) {
            info->mean_bitrate = (int)enc->mean_bitrate;
            changed = 1;
        }
        if (info->max_bitrate != (int)enc->max_bitrate &&
            codecapi_update_u32(enc, &MF_API_AVEncCommonMaxBitRate, enc->max_bitrate, "max-bitrate")) {
            info->max_bitrate = (int)enc->max_bitrate;
            changed = 1;
        }
    }

    if (info->quality_vs_speed != 100 - speed &&
        codecapi_update_u32(enc, &MF_API_AVEncCommonQualityVsSpeed, (UINT32)(100 - speed), "quality-vs-speed")) {
        info->quality_vs_speed = 100 - speed;
        changed = 1;
    }

    return changed ? MF_ENC_OK : MF_ENC_NOT_AVAILABLE;
}

void mf_encoder_get_tuning_info(MFEncoder *enc, MFTuningInfo *info) {
    if (!info)
        return;
    if (!enc) {
        reset_tuning_info(info);
        return;
    }
    *info = enc->applied;
}

/* ── encoding ────────────────────────────────────────────────────── */

MFEncodeStatus mf_encoder_encode(MFEncoder *enc,
                                  const uint8_t *y_data, int y_stride,
                                  const uint8_t *u_data, int u_stride,
                                  const uint8_t *v_data, int v_stride,
                                  int width, int height,
                                  MFEncodedFrame *frame) {
    memset(frame, 0, sizeof(*frame));
    yuv420p_to_nv12(enc->nv12_buf, enc->nv12_stride,
                    y_data, y_stride, u_data, u_stride, v_data, v_stride,
                    width, height);
    return do_encode_nv12(enc, frame);
}

/* ── destroy ─────────────────────────────────────────────────────── */

void mf_encoder_destroy(MFEncoder *enc) {
    if (!enc) return;

    if (enc->codec_api)   ICodecAPI_Release(enc->codec_api);
    if (enc->transform) {
        IMFTransform_ProcessMessage(enc->transform, MFT_MESSAGE_NOTIFY_END_OF_STREAM, 0);
        IMFTransform_ProcessMessage(enc->transform, MFT_MESSAGE_NOTIFY_END_STREAMING, 0);
        IMFTransform_Release(enc->transform);
    }
    if (enc->out_sample)  IMFSample_Release(enc->out_sample);
    if (enc->out_mbuf)    IMFMediaBuffer_Release(enc->out_mbuf);
    if (enc->input_type)  IMFMediaType_Release(enc->input_type);
    if (enc->output_type) IMFMediaType_Release(enc->output_type);
    free(enc->nv12_buf);
    free(enc->encoded_buf);
    free(enc);
}

/* ── diagnostics ─────────────────────────────────────────────────── */

const char* mf_encode_status_str(MFEncodeStatus status) {
    switch (status) {
        case MF_ENC_OK:              return "ok";
        case MF_ENC_NEED_MORE_INPUT: return "need more input";
        case MF_ENC_ERROR:           return "error";
        case MF_ENC_NOT_AVAILABLE:   return "not available";
        default:                     return "unknown";
    }
}

long mf_encoder_get_last_hr(MFEncoder *enc) {
    return enc ? (long)enc->last_hr : 0;
}

const char* mf_encoder_get_last_error(MFEncoder *enc) {
    return (enc && enc->last_error[0]) ? enc->last_error : "";
}
