/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: MediaFoundation video encoder - C API header.
 * ABOUTME: Flat C interface wrapping IMFTransform for use from Cython.
 * ABOUTME: Accepts YUV420P CPU buffers and outputs H.264 / HEVC bitstreams. */

#ifndef MF_ENCODE_H
#define MF_ENCODE_H

#include <stdint.h>
#include "mf_common.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct MFEncoder MFEncoder;

typedef enum {
    MF_ENC_OK              =  0,
    MF_ENC_NEED_MORE_INPUT =  1,  /* encoder buffering; no output produced yet */
    MF_ENC_ERROR           = -1,
    MF_ENC_NOT_AVAILABLE   = -2,  /* codec not supported on this system */
} MFEncodeStatus;

typedef struct {
    uint8_t *data;       /* encoded bitstream (owned by encoder; valid until next encode call) */
    int      data_len;
    int      is_keyframe;
    int      us_input;   /* ProcessInput latency in microseconds */
    int      us_output;  /* ProcessOutput latency in microseconds */
} MFEncodedFrame;

/* Global init / shutdown (call once per process) */
MFEncodeStatus mf_encode_startup(void);
void           mf_encode_shutdown(void);

/* Lifecycle */
MFEncodeStatus mf_encoder_create(MFEncoder **out, int codec, int width, int height);
void           mf_encoder_destroy(MFEncoder *enc);

/* Encode one YUV420P frame (3 separate planes with independent strides).
   On MF_ENC_OK, frame->data / frame->data_len are populated; caller must
   copy before the next encode call (the buffer is reused).
   On MF_ENC_NEED_MORE_INPUT, the encoder is buffering; frame is zeroed. */
MFEncodeStatus mf_encoder_encode(MFEncoder *enc,
                                  const uint8_t *y_data, int y_stride,
                                  const uint8_t *u_data, int u_stride,
                                  const uint8_t *v_data, int v_stride,
                                  int width, int height,
                                  MFEncodedFrame *frame);

/* Diagnostics */
const char*    mf_encode_status_str(MFEncodeStatus status);
long           mf_encoder_get_last_hr(MFEncoder *enc);
const char*    mf_encoder_get_last_error(MFEncoder *enc);

/* Set before calling any other encoder functions */
void           mf_encode_set_log(mf_log_fn fn);

#ifdef __cplusplus
}
#endif

#endif /* MF_ENCODE_H */
