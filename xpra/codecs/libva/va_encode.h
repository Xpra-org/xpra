/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: libva H.264 encoder - C API header.
 * ABOUTME: Flat C interface wrapping VA-API for use from Cython. */

#ifndef XPRA_LIBVA_ENCODE_H
#define XPRA_LIBVA_ENCODE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct LibVAEncoder LibVAEncoder;

typedef enum {
    LIBVA_ENC_OK              =  0,
    LIBVA_ENC_ERROR           = -1,
    LIBVA_ENC_NOT_AVAILABLE   = -2,
} LibVAEncodeStatus;

typedef enum {
    LIBVA_ENC_FRAME_UNKNOWN = 0,
    LIBVA_ENC_FRAME_IDR     = 1,
    LIBVA_ENC_FRAME_I       = 2,
} LibVAEncodeFrameType;

typedef struct {
    uint8_t *data;
    int      size;
    LibVAEncodeFrameType frame_type;
    int      us_copy;
    int      us_submit;
    int      us_sync;
} LibVAEncodedFrame;

typedef void (*libva_log_fn)(const char *msg);

void              libva_encode_set_log(libva_log_fn fn);
LibVAEncodeStatus libva_encode_startup(void);
void              libva_encode_shutdown(void);
const char       *libva_encode_get_device(void);
const char       *libva_encode_get_vendor(void);
const char       *libva_encode_get_last_error(void);
int               libva_encode_get_major(void);
int               libva_encode_get_minor(void);

LibVAEncodeStatus libva_encoder_create(LibVAEncoder **out, int width, int height,
                                       int quality, int speed);
void              libva_encoder_destroy(LibVAEncoder *enc);
LibVAEncodeStatus libva_encoder_encode(LibVAEncoder *enc,
                                       const uint8_t *y, int y_stride,
                                       const uint8_t *uv, int uv_stride,
                                       LibVAEncodedFrame *frame);

int               libva_encoder_get_width(LibVAEncoder *enc);
int               libva_encoder_get_height(LibVAEncoder *enc);
int               libva_encoder_get_last_status(LibVAEncoder *enc);
const char       *libva_encoder_get_last_error(LibVAEncoder *enc);
const char       *libva_encode_status_str(LibVAEncodeStatus status);

#ifdef __cplusplus
}
#endif

#endif /* XPRA_LIBVA_ENCODE_H */
