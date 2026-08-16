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
    int      delayed;    /* frames the encoder is still holding on to */
    int      us_input;   /* microseconds spent staging the frame for the MFT */
    int      us_output;  /* microseconds spent in the MFT, waiting for this frame */
} MFEncodedFrame;

/* What the window is showing, mapped from xpra's content-type.
   Anything that isn't positively identified as continuous tone is treated as
   screen content, which is what an xpra window is until proven otherwise. */
typedef enum {
    MF_CONTENT_UNKNOWN = 0,
    MF_CONTENT_SCREEN  = 1,  /* synthetic edges: text, browser, desktop */
    MF_CONTENT_VIDEO   = 2,  /* continuous tone: real video, photos */
} MFContentType;

typedef enum {
    MF_ENC_PROFILE_CONSTRAINED_BASELINE = 0,
    MF_ENC_PROFILE_MAIN                 = 1,
    MF_ENC_PROFILE_HIGH                 = 2,
} MFEncodeProfile;

/* What the encoder should aim for. Every value is a request: which of them the
   MFT honours depends on the (hardware) encoder behind it, and what was really
   applied is reported by `mf_encoder_get_tuning_info`. */
typedef struct {
    int content_type;      /* MFContentType */
    int quality;           /* 0 (worst) .. 100 (best) */
    int speed;             /* 0 (slowest) .. 100 (fastest) */
    int bandwidth_limit;   /* bits per second, 0 if unlimited */
    MFEncodeProfile profile; /* requested H.264 profile; ignored for HEVC */
} MFEncoderTuning;

/* The tuning that was actually applied: -1 means the MFT does not expose that
   knob, or rejected the value we asked for. */
typedef struct {
    int codec_api;         /* 1 if the MFT exposes ICodecAPI at all */
    int rate_control;      /* eAVEncCommonRateControlMode */
    int mean_bitrate;      /* bits per second */
    int max_bitrate;       /* bits per second */
    int quality;           /* AVEncCommonQuality, 0..100 */
    int quality_vs_speed;  /* AVEncCommonQualityVsSpeed, 0 (speed) .. 100 (quality) */
    int gop_size;          /* frames between keyframes */
    int bframes;           /* number of B pictures */
    int low_latency;       /* 1 if any of the low-latency hints was accepted */
    int content_type;      /* AVEncVideoContentType */
    int adaptive_mode;     /* AVEncAdaptiveMode */
    int cabac;             /* H.264 only */
    int profile;           /* MF_MT_MPEG2_PROFILE value used for the output type */
} MFTuningInfo;

/* Global init / shutdown (call once per process) */
MFEncodeStatus mf_encode_startup(void);
void           mf_encode_shutdown(void);

/* Lifecycle - `tuning` may be NULL for the defaults */
MFEncodeStatus mf_encoder_create(MFEncoder **out, int codec, int width, int height,
                                 const MFEncoderTuning *tuning);
void           mf_encoder_destroy(MFEncoder *enc);

/* Update the quality / speed / bandwidth limit of a running encoder.
   The content type is *not* updated: it selects the rate control mode, the GOP
   length and the encoder's own content hint, none of which can be changed on an
   open MFT - create a new encoder for that.
   Returns MF_ENC_OK if at least one knob was applied, MF_ENC_NOT_AVAILABLE if
   this MFT only accepts them at creation time. */
MFEncodeStatus mf_encoder_set_tuning(MFEncoder *enc, const MFEncoderTuning *tuning);

/* What the encoder is really doing (for logging and `get_info`) */
void           mf_encoder_get_tuning_info(MFEncoder *enc, MFTuningInfo *info);
const char*    mf_rate_control_str(int rate_control);

/* Encode one YUV420P frame (3 separate planes with independent strides).
   On MF_ENC_OK, frame->data / frame->data_len are populated; caller must
   copy before the next encode call (the buffer is reused).
   On MF_ENC_NEED_MORE_INPUT, the encoder is buffering; frame->delayed says how
   many frames it is holding, which `mf_encoder_flush` can ask it for. */
MFEncodeStatus mf_encoder_encode(MFEncoder *enc,
                                  const uint8_t *y_data, int y_stride,
                                  const uint8_t *u_data, int u_stride,
                                  const uint8_t *v_data, int v_stride,
                                  int width, int height,
                                  MFEncodedFrame *frame);

/* Ask for one frame the encoder is still holding, draining the MFT if it has
   to. Draining ends the stream segment, so the next encoded frame will be an
   IDR - only worth doing when no more frames are coming for a while.
   Returns MF_ENC_NEED_MORE_INPUT if there was nothing left to hand over. */
MFEncodeStatus mf_encoder_flush(MFEncoder *enc, MFEncodedFrame *frame);

/* Diagnostics */
const char*    mf_encode_status_str(MFEncodeStatus status);
long           mf_encoder_get_last_hr(MFEncoder *enc);
const char*    mf_encoder_get_last_error(MFEncoder *enc);
const char*    mf_encoder_get_name(MFEncoder *enc);      /* MFT friendly name */
int            mf_encoder_is_hardware(MFEncoder *enc);   /* 1 for a hardware MFT */
/* 1 once a hardware MFT has stopped answering: they are not used again after
   that, and the one that wedged is deliberately never released */
int            mf_hardware_wedged(void);

/* Set before calling any other encoder functions */
void           mf_encode_set_log(mf_log_fn fn);

#ifdef __cplusplus
}
#endif

#endif /* MF_ENCODE_H */
