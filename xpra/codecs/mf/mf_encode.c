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
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>

#ifndef MF_LOW_LATENCY
DEFINE_GUID(MF_LOW_LATENCY, 0x9c27891a, 0xed7a, 0x40e1,
            0x88, 0xe8, 0xb2, 0x27, 0x27, 0xa0, 0x24, 0xee);
#endif

struct MFEncoder {
    IMFTransform   *transform;
    IMFMediaType   *input_type;
    IMFMediaType   *output_type;
    /* pre-allocated output sample for MFTs that don't provide their own */
    IMFSample      *out_sample;
    IMFMediaBuffer *out_mbuf;
    int             provides_samples;
    int             width;
    int             height;
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

/* ── YUV420P → NV12 conversion ───────────────────────────────────── */

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

MFEncodeStatus mf_encoder_create(MFEncoder **out, int codec, int width, int height) {
    HRESULT hr;
    MFEncoder *enc;
    IMFActivate **activates = NULL;
    UINT32 num_activates = 0;
    MFT_REGISTER_TYPE_INFO output_info;
    DWORD i;
    const GUID *out_subtype;
    DWORD bitrate;

    *out = NULL;

    out_subtype = enc_codec_to_subtype(codec);
    if (!out_subtype)
        return MF_ENC_NOT_AVAILABLE;

    enc = (MFEncoder *)calloc(1, sizeof(MFEncoder));
    if (!enc)
        return MF_ENC_ERROR;

    enc->width  = width;
    enc->height = height;

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

    /* compute a resolution-appropriate bitrate, clamped to [500k, 20M] bps */
    bitrate = (DWORD)((unsigned long long)width * height * 30 / 10);
    if (bitrate < 500000)   bitrate = 500000;
    if (bitrate > 20000000) bitrate = 20000000;
    enc_log("mf_encoder_create: bitrate=%lu bps", (unsigned long)bitrate);

    /* set output type (compressed format) — must precede input type for encoders */
    hr = MFCreateMediaType(&enc->output_type);
    if (FAILED(hr)) { set_enc_error(enc, hr, "MFCreateMediaType(output)"); goto fail; }

    IMFMediaType_SetGUID(enc->output_type,   &MF_MT_MAJOR_TYPE,        &MFMediaType_Video);
    IMFMediaType_SetGUID(enc->output_type,   &MF_MT_SUBTYPE,           out_subtype);
    IMFMediaType_SetUINT64(enc->output_type, &MF_MT_FRAME_SIZE,        ((UINT64)width << 32) | (UINT64)height);
    IMFMediaType_SetUINT32(enc->output_type, &MF_MT_INTERLACE_MODE,    MFVideoInterlace_Progressive);
    IMFMediaType_SetUINT64(enc->output_type, &MF_MT_FRAME_RATE,        ((UINT64)30 << 32) | 1ULL);
    IMFMediaType_SetUINT64(enc->output_type, &MF_MT_PIXEL_ASPECT_RATIO,((UINT64)1  << 32) | 1ULL);
    IMFMediaType_SetUINT32(enc->output_type, &MF_MT_AVG_BITRATE,       bitrate);

    hr = IMFTransform_SetOutputType(enc->transform, 0, enc->output_type, 0);
    if (FAILED(hr)) {
        enc_log("mf_encoder_create: SetOutputType(%s) failed: 0x%08lX",
                enc_codec_to_name(codec), (unsigned long)hr);
        goto fail;
    }
    enc_log("mf_encoder_create: output type set (%s, %dx%d, %lubps)",
            enc_codec_to_name(codec), width, height, (unsigned long)bitrate);

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
                IMFMediaType_SetUINT64(candidate, &MF_MT_FRAME_RATE,        ((UINT64)30 << 32) | 1ULL);

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

    /* allocate NV12 scratch buffer (stride aligned to 16 bytes) */
    enc->nv12_stride   = (width + 15) & ~15;
    enc->nv12_buf_size = enc->nv12_stride * height * 3 / 2;
    enc->nv12_buf      = (uint8_t *)malloc((size_t)enc->nv12_buf_size);
    if (!enc->nv12_buf) {
        enc_log("mf_encoder_create: malloc nv12_buf failed");
        goto fail;
    }

    enc_log("mf_encoder_create: encoder ready (%dx%d nv12_stride=%d provides_samples=%d)",
            width, height, enc->nv12_stride, enc->provides_samples);
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

    /* timestamps at 30 fps in 100-ns units */
    IMFSample_SetSampleTime(in_sample,     enc->frame_count * 333333LL);
    IMFSample_SetSampleDuration(in_sample, 333333LL);

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
