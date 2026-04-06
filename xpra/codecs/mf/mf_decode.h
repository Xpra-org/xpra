/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: MediaFoundation H.264 hardware decoder - C API header.
 * ABOUTME: Flat C interface wrapping IMFTransform for use from Cython. */

#ifndef MF_DECODE_H
#define MF_DECODE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct MFDecoder MFDecoder;

typedef enum {
    MF_DEC_OK              =  0,
    MF_DEC_NEED_MORE_INPUT =  1,
    MF_DEC_STREAM_CHANGE   =  2,
    MF_DEC_ERROR           = -1,
    MF_DEC_NOT_AVAILABLE   = -2,
} MFDecodeStatus;

typedef struct {
    uint8_t *y_data;
    uint8_t *uv_data;      /* NV12 interleaved UV plane */
    int      y_stride;
    int      uv_stride;
    int      width;
    int      height;
    int      full_range;
    /* timing breakdown in microseconds */
    int      us_input;      /* ProcessInput */
    int      us_output;     /* ProcessOutput (includes GPU decode + sync) */
    int      us_extract;    /* ConvertToContiguousBuffer + Lock (GPU→CPU copy) */
} MFDecodedFrame;

/* Global init / shutdown (call once per process) */
MFDecodeStatus mf_decode_startup(void);
void           mf_decode_shutdown(void);

/* Supported codec identifiers */
#define MF_CODEC_H264  0
#define MF_CODEC_HEVC  1
#define MF_CODEC_VP9   2
#define MF_CODEC_AV1   3

/* Lifecycle */
MFDecodeStatus mf_decoder_create(MFDecoder **out, int codec, int width, int height);
void           mf_decoder_destroy(MFDecoder *dec);

/* Decode one compressed video access unit.
   On MF_DEC_OK, frame is populated; caller must copy before next call.
   On MF_DEC_NEED_MORE_INPUT, frame is zeroed.
   On MF_DEC_STREAM_CHANGE, dimensions changed; call mf_decoder_get_output_size(). */
MFDecodeStatus mf_decoder_decode(MFDecoder *dec,
                                  const uint8_t *data, int data_len,
                                  MFDecodedFrame *frame);

/* Drain buffered frames after end of stream */
MFDecodeStatus mf_decoder_flush(MFDecoder *dec, MFDecodedFrame *frame);

/* Query current output dimensions */
void mf_decoder_get_output_size(MFDecoder *dec, int *width, int *height);

/* Info / diagnostics */
int            mf_decoder_is_hardware(MFDecoder *dec);
const char*    mf_decode_status_str(MFDecodeStatus status);
long           mf_decoder_get_last_hr(MFDecoder *dec);
const char*    mf_decoder_get_last_error(MFDecoder *dec);

/* Logging callback — set before calling any other functions.
   The C layer calls this for diagnostic messages. */
typedef void (*mf_log_fn)(const char *msg);
void           mf_decode_set_log(mf_log_fn fn);

#ifdef __cplusplus
}
#endif

#endif /* MF_DECODE_H */
