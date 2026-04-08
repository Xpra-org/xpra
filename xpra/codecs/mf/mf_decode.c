/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: MediaFoundation H.264 hardware decoder - C implementation.
 * ABOUTME: Manages COM lifetime, MFT enumeration, and NV12 frame extraction. */

#include "mf_decode.h"

#define COBJMACROS
#include <windows.h>
#include <mfapi.h>
#include <mftransform.h>
#include <mfidl.h>
#include <mferror.h>
#include <codecapi.h>
#include <d3d11.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

/* MF_LOW_LATENCY may not be defined in older SDK headers.
   GUID from https://learn.microsoft.com/en-us/windows/win32/medfound/mf-low-latency */
#ifndef MF_LOW_LATENCY
DEFINE_GUID(MF_LOW_LATENCY, 0x9c27891a, 0xed7a, 0x40e1,
            0x88, 0xe8, 0xb2, 0x27, 0x27, 0xa0, 0x24, 0xee);
#endif

struct MFDecoder {
    IMFTransform    *transform;
    IMFMediaType    *input_type;
    IMFMediaType    *output_type;
    IMFSample       *output_sample;   /* reusable output sample (for MFTs that don't allocate) */
    IMFMediaBuffer  *output_buffer;   /* backing buffer for output_sample */
    IMFMediaBuffer  *locked_buffer;   /* currently locked output buffer, if any */
    int              locked_is_2d;    /* locked_buffer is actually an IMF2DBuffer */
    IMFSample       *locked_sample;   /* MFT-provided sample to release after copy */
    ID3D11Device    *d3d_device;      /* D3D11 device for DXVA hardware decode */
    IMFDXGIDeviceManager *dxgi_manager; /* DXGI device manager passed to the MFT */
    UINT             dxgi_reset_token; /* token from MFCreateDXGIDeviceManager */
    int              width;
    int              height;
    int              is_hw;
    int              provides_samples; /* MFT allocates its own output samples */
    HRESULT          last_hr;         /* last failing HRESULT for diagnostics */
    char             last_error[128]; /* human-readable description of last error */
};

static int  g_com_owned = 0;
static int  g_mf_started = 0;
static mf_log_fn g_log_fn = NULL;

/* ── logging and error helpers ───────────────────────────────────── */

void mf_decode_set_log(mf_log_fn fn) {
    g_log_fn = fn;
}

static void mf_log(const char *fmt, ...) {
    if (!g_log_fn)
        return;
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    g_log_fn(buf);
}

static MFDecodeStatus set_error(MFDecoder *dec, HRESULT hr, const char *context) {
    if (dec) {
        dec->last_hr = hr;
        snprintf(dec->last_error, sizeof(dec->last_error),
                 "%s failed: HRESULT 0x%08lX", context, (unsigned long)hr);
        mf_log("mf error: %s", dec->last_error);
    }
    return MF_DEC_ERROR;
}

static LARGE_INTEGER g_perf_freq = {0};

static long long usec_now(void) {
    LARGE_INTEGER now;
    if (g_perf_freq.QuadPart == 0)
        QueryPerformanceFrequency(&g_perf_freq);
    QueryPerformanceCounter(&now);
    return (long long)(now.QuadPart * 1000000 / g_perf_freq.QuadPart);
}

/* ── helpers ─────────────────────────────────────────────────────── */

/* Release any locked buffer/sample from a previous decode call.
   Called before each new decode and during destroy. */
static void clear_locked(MFDecoder *dec) {
    if (dec->locked_buffer) {
        if (dec->locked_is_2d) {
            IMF2DBuffer_Unlock2D((IMF2DBuffer *)dec->locked_buffer);
        } else {
            IMFMediaBuffer_Unlock(dec->locked_buffer);
        }
        IMFMediaBuffer_Release(dec->locked_buffer);
        dec->locked_buffer = NULL;
        dec->locked_is_2d = 0;
    }
    if (dec->locked_sample) {
        IMFSample_Release(dec->locked_sample);
        dec->locked_sample = NULL;
    }
}

static void zero_frame(MFDecodedFrame *frame) {
    memset(frame, 0, sizeof(*frame));
}

/* Get padded dimensions from the output media type */
static void get_padded_size(MFDecoder *dec, int *padded_w, int *padded_h) {
    *padded_w = dec->width;
    *padded_h = dec->height;
    UINT64 out_frame_size = 0;
    if (SUCCEEDED(IMFMediaType_GetUINT64(dec->output_type, &MF_MT_FRAME_SIZE, &out_frame_size))) {
        *padded_w = (int)(out_frame_size >> 32);
        *padded_h = (int)(out_frame_size & 0xFFFFFFFF);
    }
}

/* Try IMF2DBuffer::Lock2D for direct access to the GPU staging texture.
   This avoids the intermediate buffer allocation that ConvertToContiguousBuffer creates.
   Returns 1 on success, 0 if IMF2DBuffer is not available (fall back to 1D path). */
static int try_extract_2d(MFDecoder *dec, IMFSample *sample, MFDecodedFrame *frame) {
    HRESULT hr;
    IMFMediaBuffer *raw_buf = NULL;
    IMF2DBuffer *buf2d = NULL;
    BYTE *data = NULL;
    LONG pitch = 0;
    int padded_w, padded_h;

    hr = IMFSample_GetBufferByIndex(sample, 0, &raw_buf);
    if (FAILED(hr))
        return 0;

    hr = IMFMediaBuffer_QueryInterface(raw_buf, &IID_IMF2DBuffer, (void **)&buf2d);
    IMFMediaBuffer_Release(raw_buf);
    if (FAILED(hr))
        return 0;

    hr = IMF2DBuffer_Lock2D(buf2d, &data, &pitch);
    if (FAILED(hr)) {
        IMF2DBuffer_Release(buf2d);
        return 0;
    }

    /* Lock2D gives us the pointer and stride directly from the mapped surface */
    get_padded_size(dec, &padded_w, &padded_h);

    frame->width     = padded_w;
    frame->height    = padded_h;
    frame->y_stride  = (pitch < 0) ? -pitch : pitch;
    frame->y_data    = (uint8_t *)data;
    frame->uv_data   = (uint8_t *)data + frame->y_stride * padded_h;
    frame->uv_stride = frame->y_stride;

    /* keep the 2D buffer locked; store as locked_buffer for cleanup.
       IMF2DBuffer inherits from IMFMediaBuffer so this cast is safe. */
    dec->locked_buffer = (IMFMediaBuffer *)buf2d;
    dec->locked_is_2d = 1;

    mf_log("mf extract(2D): %dx%d stride=%d (pitch=%ld)", padded_w, padded_h, frame->y_stride, (long)pitch);
    return 1;
}

/* Fallback: ConvertToContiguousBuffer for MFTs that don't support IMF2DBuffer */
static MFDecodeStatus extract_1d(MFDecoder *dec, IMFSample *sample, MFDecodedFrame *frame) {
    HRESULT hr;
    IMFMediaBuffer *buf = NULL;
    BYTE *data = NULL;
    DWORD max_len = 0, cur_len = 0;
    DWORD expected_size;
    int padded_w, padded_h;

    hr = IMFSample_ConvertToContiguousBuffer(sample, &buf);
    if (FAILED(hr))
        return set_error(dec, hr, "ConvertToContiguousBuffer");

    hr = IMFMediaBuffer_Lock(buf, &data, &max_len, &cur_len);
    if (FAILED(hr)) {
        IMFMediaBuffer_Release(buf);
        return set_error(dec, hr, "IMFMediaBuffer_Lock");
    }

    dec->locked_buffer = buf;
    get_padded_size(dec, &padded_w, &padded_h);

    frame->width  = padded_w;
    frame->height = padded_h;

    /* determine stride from media type or buffer size */
    UINT32 raw_stride = 0;
    hr = IMFMediaType_GetUINT32(dec->output_type, &MF_MT_DEFAULT_STRIDE, &raw_stride);
    if (SUCCEEDED(hr) && raw_stride != 0) {
        INT32 signed_stride = (INT32)raw_stride;
        frame->y_stride = (signed_stride < 0) ? -signed_stride : signed_stride;
    } else if (padded_h > 0) {
        frame->y_stride = (int)(cur_len * 2 / (padded_h * 3));
    } else {
        frame->y_stride = (padded_w + 15) & ~15;
    }
    expected_size = (DWORD)(frame->y_stride * padded_h * 3 / 2);
    if (cur_len < expected_size) {
        mf_log("mf extract(1D): buffer too small: %lu < %lu (stride=%d, %dx%d)",
               (unsigned long)cur_len, (unsigned long)expected_size,
               frame->y_stride, padded_w, padded_h);
        IMFMediaBuffer_Unlock(buf);
        IMFMediaBuffer_Release(buf);
        dec->locked_buffer = NULL;
        snprintf(dec->last_error, sizeof(dec->last_error),
                 "NV12 buffer too small: %lu < %lu", (unsigned long)cur_len, (unsigned long)expected_size);
        dec->last_hr = E_FAIL;
        return MF_DEC_ERROR;
    }

    frame->y_data   = (uint8_t *)data;
    frame->uv_data  = (uint8_t *)data + frame->y_stride * padded_h;
    frame->uv_stride = frame->y_stride;

    mf_log("mf extract(1D): %dx%d stride=%d cur_len=%lu", padded_w, padded_h,
           frame->y_stride, (unsigned long)cur_len);
    return MF_DEC_OK;
}

/* Populate frame pointers from an NV12 output sample.
   NV12 is a semi-planar format: Y plane (height rows of y_stride bytes)
   followed immediately by interleaved UV plane (height/2 rows of uv_stride bytes).
   Tries IMF2DBuffer first (direct GPU staging texture access, avoids extra copy),
   falls back to ConvertToContiguousBuffer if unavailable. */
static MFDecodeStatus extract_nv12(MFDecoder *dec, IMFSample *sample, MFDecodedFrame *frame) {
    HRESULT hr;
    long long t0, t1;
    MFDecodeStatus st;

    clear_locked(dec);
    zero_frame(frame);

    t0 = usec_now();

    if (try_extract_2d(dec, sample, frame)) {
        st = MF_DEC_OK;
    } else {
        st = extract_1d(dec, sample, frame);
    }

    t1 = usec_now();
    frame->us_extract = (int)(t1 - t0);

    if (st == MF_DEC_OK) {
        /* check for full-range YUV */
        UINT32 nom_range = 0;
        hr = IMFMediaType_GetUINT32(dec->output_type, &MF_MT_VIDEO_NOMINAL_RANGE, &nom_range);
        frame->full_range = (SUCCEEDED(hr) && nom_range == MFNominalRange_0_255) ? 1 : 0;

        mf_log("mf extract: %dx%d stride=%d extract=%dus full_range=%d",
               frame->width, frame->height, frame->y_stride,
               frame->us_extract, frame->full_range);
    }

    return st;
}

/* Max retries for stream-change renegotiation before giving up */
#define MAX_OUTPUT_RETRIES 3

/* Pull one decoded frame from the MFT via ProcessOutput.
   Allocates an output sample if the MFT doesn't provide its own.
   Handles stream format changes (resolution/type renegotiation). */
static MFDecodeStatus try_get_output(MFDecoder *dec, MFDecodedFrame *frame) {
    HRESULT hr;
    MFT_OUTPUT_DATA_BUFFER out_buf;
    DWORD status = 0;
    int retries = 0;

retry_output:
    memset(&out_buf, 0, sizeof(out_buf));
    out_buf.dwStreamID = 0;

    if (!dec->provides_samples) {
        /* Software MFTs and some hardware MFTs don't allocate output samples.
           We must provide a sample+buffer for ProcessOutput to write into.
           The sample is reused across calls; reallocated on stream change. */
        if (!dec->output_sample) {
            DWORD buf_size = 0;
            MFT_OUTPUT_STREAM_INFO stream_info;
            memset(&stream_info, 0, sizeof(stream_info));
            hr = IMFTransform_GetOutputStreamInfo(dec->transform, 0, &stream_info);
            if (FAILED(hr))
                return set_error(dec, hr, "GetOutputStreamInfo");
            buf_size = stream_info.cbSize;
            if (buf_size == 0)
                buf_size = dec->width * dec->height * 3 / 2;  /* NV12 size */

            mf_log("mf output: allocating output sample, buf_size=%lu", (unsigned long)buf_size);
            hr = MFCreateMemoryBuffer(buf_size, &dec->output_buffer);
            if (FAILED(hr))
                return set_error(dec, hr, "MFCreateMemoryBuffer(output)");
            hr = MFCreateSample(&dec->output_sample);
            if (FAILED(hr)) {
                IMFMediaBuffer_Release(dec->output_buffer);
                dec->output_buffer = NULL;
                return set_error(dec, hr, "MFCreateSample(output)");
            }
            hr = IMFSample_AddBuffer(dec->output_sample, dec->output_buffer);
            if (FAILED(hr)) {
                IMFSample_Release(dec->output_sample);
                dec->output_sample = NULL;
                IMFMediaBuffer_Release(dec->output_buffer);
                dec->output_buffer = NULL;
                return set_error(dec, hr, "IMFSample_AddBuffer(output)");
            }
        }
        /* reset buffer length before reuse — MFT expects an empty buffer */
        if (dec->output_buffer)
            IMFMediaBuffer_SetCurrentLength(dec->output_buffer, 0);
        out_buf.pSample = dec->output_sample;
    }

    hr = IMFTransform_ProcessOutput(dec->transform, 0, 1, &out_buf, &status);
    mf_log("mf ProcessOutput: hr=0x%08lX status=0x%lX provides_samples=%d",
           (unsigned long)hr, (unsigned long)status, dec->provides_samples);

    if (hr == MF_E_TRANSFORM_NEED_MORE_INPUT) {
        zero_frame(frame);
        return MF_DEC_NEED_MORE_INPUT;
    }

    if (hr == MF_E_TRANSFORM_STREAM_CHANGE) {
        /* renegotiate output type, then retry ProcessOutput */
        DWORD i;
        int renegotiated = 0;
        for (i = 0; ; i++) {
            IMFMediaType *new_type = NULL;
            hr = IMFTransform_GetOutputAvailableType(dec->transform, 0, i, &new_type);
            if (FAILED(hr))
                break;

            GUID new_subtype;
            IMFMediaType_GetGUID(new_type, &MF_MT_SUBTYPE, &new_subtype);
            mf_log("mf stream change: available type %lu: {%08lX-%04X-%04X-...}",
                   (unsigned long)i, (unsigned long)new_subtype.Data1,
                   (unsigned)new_subtype.Data2, (unsigned)new_subtype.Data3);
            if (IsEqualGUID(&new_subtype, &MFVideoFormat_NV12)) {
                hr = IMFTransform_SetOutputType(dec->transform, 0, new_type, 0);
                if (FAILED(hr)) {
                    IMFMediaType_Release(new_type);
                    return set_error(dec, hr, "SetOutputType(stream change)");
                }
                if (dec->output_type)
                    IMFMediaType_Release(dec->output_type);
                dec->output_type = new_type;

                /* update dimensions */
                UINT64 frame_size = 0;
                if (SUCCEEDED(IMFMediaType_GetUINT64(new_type, &MF_MT_FRAME_SIZE, &frame_size))) {
                    dec->width  = (int)(frame_size >> 32);
                    dec->height = (int)(frame_size & 0xFFFFFFFF);
                }

                /* free old output sample since buffer size may have changed */
                if (dec->output_sample) {
                    IMFSample_Release(dec->output_sample);
                    dec->output_sample = NULL;
                }
                if (dec->output_buffer) {
                    IMFMediaBuffer_Release(dec->output_buffer);
                    dec->output_buffer = NULL;
                }

                renegotiated = 1;
                break;
            }
            IMFMediaType_Release(new_type);
        }
        if (!renegotiated) {
            snprintf(dec->last_error, sizeof(dec->last_error), "stream change: NV12 not available");
            dec->last_hr = MF_E_INVALIDMEDIATYPE;
            mf_log("mf error: %s", dec->last_error);
            return MF_DEC_ERROR;
        }
        mf_log("mf stream change: renegotiated to %dx%d", dec->width, dec->height);
        /* input was already consumed; retry output with new type */
        if (++retries >= MAX_OUTPUT_RETRIES) {
            snprintf(dec->last_error, sizeof(dec->last_error), "stream change: too many retries (%d)", retries);
            dec->last_hr = E_FAIL;
            mf_log("mf error: %s", dec->last_error);
            return MF_DEC_ERROR;
        }
        goto retry_output;
    }

    if (FAILED(hr))
        return set_error(dec, hr, "ProcessOutput");

    /* success - extract NV12 data */
    IMFSample *result_sample = out_buf.pSample;
    MFDecodeStatus ret = extract_nv12(dec, result_sample, frame);

    /* hold MFT-provided sample until clear_locked() releases the buffer */
    if (dec->provides_samples && result_sample) {
        dec->locked_sample = result_sample;
    }

    return ret;
}

/* ── public API ──────────────────────────────────────────────────── */

MFDecodeStatus mf_decode_startup(void) {
    HRESULT hr;

    mf_log("mf_decode_startup: initializing COM");
    hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    if (hr == RPC_E_CHANGED_MODE) {
        mf_log("mf_decode_startup: COM already initialized (STA), reusing");
        g_com_owned = 0;
    } else if (FAILED(hr)) {
        mf_log("mf_decode_startup: CoInitializeEx failed: 0x%08lX", (unsigned long)hr);
        return MF_DEC_ERROR;
    } else {
        mf_log("mf_decode_startup: COM initialized (MTA)");
        g_com_owned = 1;
    }

    hr = MFStartup(MF_VERSION, MFSTARTUP_LITE);
    if (FAILED(hr)) {
        mf_log("mf_decode_startup: MFStartup failed: 0x%08lX", (unsigned long)hr);
        if (g_com_owned)
            CoUninitialize();
        g_com_owned = 0;
        return MF_DEC_ERROR;
    }

    mf_log("mf_decode_startup: MediaFoundation started successfully");
    g_mf_started = 1;
    return MF_DEC_OK;
}

void mf_decode_shutdown(void) {
    if (g_mf_started) {
        MFShutdown();
        g_mf_started = 0;
    }
    if (g_com_owned) {
        CoUninitialize();
        g_com_owned = 0;
    }
}

static const GUID* codec_to_subtype(int codec) {
    switch (codec) {
        case MF_CODEC_H264: return &MFVideoFormat_H264;
        case MF_CODEC_HEVC: return &MFVideoFormat_HEVC;
        case MF_CODEC_VP9:  return &MFVideoFormat_VP90;
        case MF_CODEC_AV1:  return &MFVideoFormat_AV1;
        default:            return NULL;
    }
}

static const char* codec_to_name(int codec) {
    switch (codec) {
        case MF_CODEC_H264: return "H.264";
        case MF_CODEC_HEVC: return "HEVC";
        case MF_CODEC_VP9:  return "VP9";
        case MF_CODEC_AV1:  return "AV1";
        default:            return "unknown";
    }
}

MFDecodeStatus mf_decoder_create(MFDecoder **out, int codec, int width, int height) {
    HRESULT hr;
    MFDecoder *dec;
    IMFActivate **activates = NULL;
    UINT32 num_activates = 0;
    MFT_REGISTER_TYPE_INFO input_info;
    DWORD i;
    const GUID *subtype;

    *out = NULL;

    subtype = codec_to_subtype(codec);
    if (!subtype)
        return MF_DEC_NOT_AVAILABLE;

    dec = (MFDecoder *)calloc(1, sizeof(MFDecoder));
    if (!dec)
        return MF_DEC_ERROR;

    dec->width  = width;
    dec->height = height;

    /* enumerate decoders for the requested codec.
       The inbox MFTs are sync MFTs that use DXVA hardware acceleration
       internally — they don't register as MFT_ENUM_FLAG_HARDWARE.
       SORTANDFILTER prefers hardware-backed MFTs when available. */
    input_info.guidMajorType = MFMediaType_Video;
    input_info.guidSubtype   = *subtype;

    mf_log("mf_decoder_create: enumerating %s decoders for %dx%d",
           codec_to_name(codec), width, height);
    hr = MFTEnumEx(MFT_CATEGORY_VIDEO_DECODER,
                   MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_SORTANDFILTER,
                   &input_info, NULL,
                   &activates, &num_activates);
    mf_log("mf_decoder_create: MFTEnumEx returned hr=0x%08lX, found %u decoders",
           (unsigned long)hr, (unsigned int)num_activates);

    if (FAILED(hr) || num_activates == 0) {
        if (activates)
            CoTaskMemFree(activates);
        free(dec);
        return MF_DEC_NOT_AVAILABLE;
    }

    /* check if the selected MFT is D3D11-aware (hardware accelerated) */
    dec->is_hw = 0;

    /* activate the first (highest-priority) MFT */
    hr = IMFActivate_ActivateObject(activates[0], &IID_IMFTransform,
                                    (void **)&dec->transform);
    /* release all activation objects — MFTEnumEx returns an array we must clean up */
    for (i = 0; i < num_activates; i++)
        IMFActivate_Release(activates[i]);
    CoTaskMemFree(activates);

    if (FAILED(hr)) {
        mf_log("mf_decoder_create: ActivateObject failed: 0x%08lX", (unsigned long)hr);
        free(dec);
        return MF_DEC_ERROR;
    }
    mf_log("mf_decoder_create: MFT activated successfully");

    /* configure MFT attributes: low-latency mode and detect hardware acceleration */
    {
        IMFAttributes *attrs = NULL;
        hr = IMFTransform_GetAttributes(dec->transform, &attrs);
        if (SUCCEEDED(hr) && attrs) {
            IMFAttributes_SetUINT32(attrs, &MF_LOW_LATENCY, TRUE);
            /* MF_SA_D3D11_AWARE indicates the MFT can use DXVA hardware decode */
            UINT32 d3d11_aware = 0;
            if (SUCCEEDED(IMFAttributes_GetUINT32(attrs, &MF_SA_D3D11_AWARE, &d3d11_aware))) {
                dec->is_hw = d3d11_aware ? 1 : 0;
            }
            IMFAttributes_Release(attrs);
        }
    }
    mf_log("mf_decoder_create: is_hw=%d (D3D11-aware)", dec->is_hw);

    /* set up D3D11 device manager for DXVA hardware acceleration.
       Without this, the MFT falls back to software CPU decode. */
    if (dec->is_hw) {
        int d3d_ok = 0;
        D3D_FEATURE_LEVEL feature_level;
        hr = D3D11CreateDevice(NULL, D3D_DRIVER_TYPE_HARDWARE, NULL,
                               D3D11_CREATE_DEVICE_VIDEO_SUPPORT,
                               NULL, 0, D3D11_SDK_VERSION,
                               &dec->d3d_device, &feature_level, NULL);
        if (FAILED(hr)) {
            mf_log("mf_decoder_create: D3D11CreateDevice failed: 0x%08lX, using software decode",
                   (unsigned long)hr);
            goto d3d_done;
        }
        mf_log("mf_decoder_create: D3D11 device created (feature level 0x%lX)",
               (unsigned long)feature_level);

        /* enable multi-threaded access on the D3D device */
        ID3D10Multithread *mt = NULL;
        hr = ID3D11Device_QueryInterface(dec->d3d_device, &IID_ID3D10Multithread, (void **)&mt);
        if (SUCCEEDED(hr) && mt) {
            ID3D10Multithread_SetMultithreadProtected(mt, TRUE);
            ID3D10Multithread_Release(mt);
        }

        hr = MFCreateDXGIDeviceManager(&dec->dxgi_reset_token, &dec->dxgi_manager);
        if (FAILED(hr)) {
            mf_log("mf_decoder_create: MFCreateDXGIDeviceManager failed: 0x%08lX", (unsigned long)hr);
            goto d3d_done;
        }
        hr = IMFDXGIDeviceManager_ResetDevice(dec->dxgi_manager,
                                               (IUnknown *)dec->d3d_device,
                                               dec->dxgi_reset_token);
        if (FAILED(hr)) {
            mf_log("mf_decoder_create: DXGI ResetDevice failed: 0x%08lX", (unsigned long)hr);
            goto d3d_done;
        }
        hr = IMFTransform_ProcessMessage(dec->transform,
                                         MFT_MESSAGE_SET_D3D_MANAGER,
                                         (ULONG_PTR)dec->dxgi_manager);
        if (FAILED(hr)) {
            mf_log("mf_decoder_create: SET_D3D_MANAGER failed: 0x%08lX, using software decode",
                   (unsigned long)hr);
            goto d3d_done;
        }
        mf_log("mf_decoder_create: DXVA hardware decode enabled");
        d3d_ok = 1;

    d3d_done:
        if (!d3d_ok) {
            /* release D3D resources — not needed for software decode */
            if (dec->dxgi_manager) {
                IMFDXGIDeviceManager_Release(dec->dxgi_manager);
                dec->dxgi_manager = NULL;
            }
            if (dec->d3d_device) {
                ID3D11Device_Release(dec->d3d_device);
                dec->d3d_device = NULL;
            }
            dec->is_hw = 0;
        }
    }

    /* configure input type: H.264 */
    hr = MFCreateMediaType(&dec->input_type);
    if (FAILED(hr)) {
        mf_log("mf_decoder_create: MFCreateMediaType failed: 0x%08lX", (unsigned long)hr);
        goto fail;
    }

    IMFMediaType_SetGUID(dec->input_type, &MF_MT_MAJOR_TYPE, &MFMediaType_Video);
    IMFMediaType_SetGUID(dec->input_type, &MF_MT_SUBTYPE, subtype);
    IMFMediaType_SetUINT64(dec->input_type, &MF_MT_FRAME_SIZE,
                           ((UINT64)width << 32) | (UINT64)height);

    hr = IMFTransform_SetInputType(dec->transform, 0, dec->input_type, 0);
    if (FAILED(hr)) {
        mf_log("mf_decoder_create: SetInputType failed: 0x%08lX", (unsigned long)hr);
        goto fail;
    }
    mf_log("mf_decoder_create: input type set (%s, %dx%d)", codec_to_name(codec), width, height);

    /* negotiate output type: look for NV12 */
    {
        int found_nv12 = 0;
        mf_log("mf_decoder_create: enumerating output types");
        for (i = 0; ; i++) {
            IMFMediaType *candidate = NULL;
            hr = IMFTransform_GetOutputAvailableType(dec->transform, 0, i, &candidate);
            if (FAILED(hr)) {
                mf_log("mf_decoder_create: GetOutputAvailableType(%lu) ended: 0x%08lX",
                       (unsigned long)i, (unsigned long)hr);
                break;
            }

            GUID out_subtype;
            IMFMediaType_GetGUID(candidate, &MF_MT_SUBTYPE, &out_subtype);
            mf_log("mf_decoder_create: output type %lu: {%08lX-%04X-%04X-...}",
                   (unsigned long)i, (unsigned long)out_subtype.Data1,
                   (unsigned)out_subtype.Data2, (unsigned)out_subtype.Data3);
            if (IsEqualGUID(&out_subtype, &MFVideoFormat_NV12)) {
                dec->output_type = candidate;
                hr = IMFTransform_SetOutputType(dec->transform, 0, candidate, 0);
                if (FAILED(hr)) {
                    mf_log("mf_decoder_create: SetOutputType(NV12) failed: 0x%08lX", (unsigned long)hr);
                    IMFMediaType_Release(candidate);
                    dec->output_type = NULL;
                    goto fail;
                }
                found_nv12 = 1;
                mf_log("mf_decoder_create: NV12 output type set");
                break;
            }
            IMFMediaType_Release(candidate);
        }
        if (!found_nv12) {
            mf_log("mf_decoder_create: NV12 not found in available output types");
            goto fail;
        }
    }

    /* check if MFT provides its own output samples */
    {
        MFT_OUTPUT_STREAM_INFO stream_info;
        memset(&stream_info, 0, sizeof(stream_info));
        hr = IMFTransform_GetOutputStreamInfo(dec->transform, 0, &stream_info);
        if (SUCCEEDED(hr)) {
            dec->provides_samples = (stream_info.dwFlags &
                (MFT_OUTPUT_STREAM_PROVIDES_SAMPLES | MFT_OUTPUT_STREAM_LAZY_READ)) ? 1 : 0;
            mf_log("mf_decoder_create: provides_samples=%d, cbSize=%lu, dwFlags=0x%lX",
                   dec->provides_samples, (unsigned long)stream_info.cbSize,
                   (unsigned long)stream_info.dwFlags);
        }
    }

    /* notify begin streaming */
    IMFTransform_ProcessMessage(dec->transform, MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
    IMFTransform_ProcessMessage(dec->transform, MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);

    mf_log("mf_decoder_create: decoder ready (%dx%d, hw=%d, provides_samples=%d)",
           dec->width, dec->height, dec->is_hw, dec->provides_samples);
    *out = dec;
    return MF_DEC_OK;

fail:
    mf_decoder_destroy(dec);
    return MF_DEC_NOT_AVAILABLE;
}

void mf_decoder_destroy(MFDecoder *dec) {
    if (!dec)
        return;

    clear_locked(dec);

    if (dec->transform) {
        /* END_OF_STREAM signals no more input; END_STREAMING tells the MFT
           to release internal resources (GPU surfaces, reference frames, etc.) */
        IMFTransform_ProcessMessage(dec->transform, MFT_MESSAGE_NOTIFY_END_OF_STREAM, 0);
        IMFTransform_ProcessMessage(dec->transform, MFT_MESSAGE_NOTIFY_END_STREAMING, 0);
    }

    if (dec->output_sample)
        IMFSample_Release(dec->output_sample);
    if (dec->output_buffer)
        IMFMediaBuffer_Release(dec->output_buffer);
    if (dec->input_type)
        IMFMediaType_Release(dec->input_type);
    if (dec->output_type)
        IMFMediaType_Release(dec->output_type);
    if (dec->transform)
        IMFTransform_Release(dec->transform);
    if (dec->dxgi_manager)
        IMFDXGIDeviceManager_Release(dec->dxgi_manager);
    if (dec->d3d_device)
        ID3D11Device_Release(dec->d3d_device);

    free(dec);
}

MFDecodeStatus mf_decoder_decode(MFDecoder *dec,
                                  const uint8_t *data, int data_len,
                                  MFDecodedFrame *frame) {
    HRESULT hr;
    IMFSample *sample = NULL;
    IMFMediaBuffer *buf = NULL;
    BYTE *buf_data = NULL;
    long long t_start, t_input_done, t_output_done;

    clear_locked(dec);
    zero_frame(frame);

    /* wrap input data in an MF sample */
    t_start = usec_now();
    hr = MFCreateMemoryBuffer((DWORD)data_len, &buf);
    if (FAILED(hr))
        return set_error(dec, hr, "MFCreateMemoryBuffer(input)");

    hr = IMFMediaBuffer_Lock(buf, &buf_data, NULL, NULL);
    if (FAILED(hr)) {
        IMFMediaBuffer_Release(buf);
        return set_error(dec, hr, "IMFMediaBuffer_Lock(input)");
    }
    memcpy(buf_data, data, data_len);
    IMFMediaBuffer_Unlock(buf);
    IMFMediaBuffer_SetCurrentLength(buf, (DWORD)data_len);

    hr = MFCreateSample(&sample);
    if (FAILED(hr)) {
        IMFMediaBuffer_Release(buf);
        return set_error(dec, hr, "MFCreateSample(input)");
    }
    IMFSample_AddBuffer(sample, buf);
    IMFMediaBuffer_Release(buf);

    /* feed to MFT */
    hr = IMFTransform_ProcessInput(dec->transform, 0, sample, 0);
    t_input_done = usec_now();

    if (hr == MF_E_NOTACCEPTING) {
        /* MFT's input buffer is full. Drain one output frame to make room,
           then re-submit our input sample (which we still hold). */
        mf_log("mf decode: MF_E_NOTACCEPTING, draining output first");
        MFDecodeStatus st = try_get_output(dec, frame);
        if (st == MF_DEC_OK) {
            /* got a decoded frame; also submit our pending input while we're here */
            hr = IMFTransform_ProcessInput(dec->transform, 0, sample, 0);
            IMFSample_Release(sample);
            if (FAILED(hr) && hr != MF_E_NOTACCEPTING)
                return set_error(dec, hr, "ProcessInput(retry after drain)");
            return MF_DEC_OK;
        }
        /* drain produced no frame; retry input now that MFT should have room */
        hr = IMFTransform_ProcessInput(dec->transform, 0, sample, 0);
        IMFSample_Release(sample);
        if (FAILED(hr))
            return set_error(dec, hr, "ProcessInput(retry)");
        return try_get_output(dec, frame);
    }

    IMFSample_Release(sample);

    if (FAILED(hr))
        return set_error(dec, hr, "ProcessInput");

    /* try to pull output */
    {
        MFDecodeStatus st = try_get_output(dec, frame);
        t_output_done = usec_now();
        frame->us_input = (int)(t_input_done - t_start);
        frame->us_output = (int)(t_output_done - t_input_done) - frame->us_extract;
        return st;
    }
}

MFDecodeStatus mf_decoder_flush(MFDecoder *dec, MFDecodedFrame *frame) {
    clear_locked(dec);
    zero_frame(frame);

    IMFTransform_ProcessMessage(dec->transform, MFT_MESSAGE_COMMAND_DRAIN, 0);
    return try_get_output(dec, frame);
}

void mf_decoder_get_output_size(MFDecoder *dec, int *width, int *height) {
    if (dec && width && height) {
        *width  = dec->width;
        *height = dec->height;
    }
}

int mf_decoder_is_hardware(MFDecoder *dec) {
    return dec ? dec->is_hw : 0;
}

const char* mf_decode_status_str(MFDecodeStatus status) {
    switch (status) {
        case MF_DEC_OK:              return "ok";
        case MF_DEC_NEED_MORE_INPUT: return "need more input";
        case MF_DEC_STREAM_CHANGE:   return "stream change";
        case MF_DEC_ERROR:           return "error";
        case MF_DEC_NOT_AVAILABLE:   return "not available";
        default:                     return "unknown";
    }
}

long mf_decoder_get_last_hr(MFDecoder *dec) {
    return dec ? (long)dec->last_hr : 0;
}

const char* mf_decoder_get_last_error(MFDecoder *dec) {
    return (dec && dec->last_error[0]) ? dec->last_error : "";
}
