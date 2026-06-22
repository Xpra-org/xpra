/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: Intel oneVPL H.264 encoder - C API header.
 * ABOUTME: Flat C interface wrapping MFXVideoENCODE for use from Cython. */

#ifndef VPL_ENCODE_H
#define VPL_ENCODE_H

#include <stdint.h>

#include "vpl_log.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct VPLEncoder VPLEncoder;

typedef enum {
    VPL_ENC_OK              =  0,
    VPL_ENC_NEED_MORE_INPUT =  1,
    VPL_ENC_ERROR           = -1,
    VPL_ENC_NOT_AVAILABLE   = -2,
} VPLEncodeStatus;

typedef enum {
    VPL_ENC_FRAME_UNKNOWN = 0,
    VPL_ENC_FRAME_IDR     = 1,
    VPL_ENC_FRAME_I       = 2,
    VPL_ENC_FRAME_P       = 3,
} VPLEncodeFrameType;

typedef enum {
    VPL_ENC_PROFILE_CONSTRAINED_BASELINE = 0,
    VPL_ENC_PROFILE_MAIN                 = 1,
    VPL_ENC_PROFILE_HIGH                 = 2,
} VPLEncodeProfile;

typedef struct {
    uint8_t *data;
    int      size;
    VPLEncodeFrameType frame_type;
    int      us_copy;
    int      us_submit;
    int      us_sync;
} VPLEncodedFrame;

VPLEncodeStatus vpl_encode_startup(void);
void            vpl_encode_shutdown(void);

VPLEncodeStatus vpl_encoder_create(VPLEncoder **out, int width, int height,
                                   int quality, int speed, VPLEncodeProfile profile);
void            vpl_encoder_destroy(VPLEncoder *enc);

VPLEncodeStatus vpl_encoder_encode(VPLEncoder *enc,
                                   const uint8_t *y, int y_stride,
                                   const uint8_t *uv, int uv_stride,
                                   VPLEncodedFrame *frame);
VPLEncodeStatus vpl_encoder_flush(VPLEncoder *enc, VPLEncodedFrame *frame);

/* Update the per-frame QP override from an xpra quality percentage (0..100).
   Effective in CQP mode only. Returns VPL_ENC_NOT_AVAILABLE in ICQ mode so
   the caller can either ignore or defer to a Reset-based reconfig path. */
VPLEncodeStatus vpl_encoder_set_quality(VPLEncoder *enc, int quality);

int             vpl_encoder_is_hardware(VPLEncoder *enc);
int             vpl_encoder_get_width(VPLEncoder *enc);
int             vpl_encoder_get_height(VPLEncoder *enc);
int             vpl_encoder_get_last_status(VPLEncoder *enc);
const char*     vpl_encoder_get_last_error(VPLEncoder *enc);
const char*     vpl_encode_status_str(VPLEncodeStatus status);

void            vpl_encode_set_log(vpl_log_fn fn);

#ifdef __cplusplus
}
#endif

#endif /* VPL_ENCODE_H */
