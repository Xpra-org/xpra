/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: libva decoder C API header.
 * ABOUTME: Flat C interface wrapping VA-API for use from Cython. */

#ifndef XPRA_LIBVA_DECODE_H
#define XPRA_LIBVA_DECODE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct LibVADecoder LibVADecoder;

typedef enum {
    LIBVA_DEC_OK              =  0,
    LIBVA_DEC_ERROR           = -1,
    LIBVA_DEC_NOT_AVAILABLE   = -2,
    LIBVA_DEC_UNSUPPORTED     = -3,
} LibVADecodeStatus;

typedef enum {
    LIBVA_DEC_FMT_UNKNOWN = 0,
    LIBVA_DEC_FMT_NV12    = 1,
    LIBVA_DEC_FMT_YUV444P = 2,
    LIBVA_DEC_FMT_XYUV    = 3,
    LIBVA_DEC_FMT_AYUV    = 4,
} LibVADecodeFormat;

typedef struct {
    uint8_t *planes[3];
    int      strides[3];
    int      sizes[3];
    int      nplanes;
    int      width;
    int      height;
    int      depth;
    int      bytes_per_pixel;
    LibVADecodeFormat format;
    int      us_submit;
    int      us_sync;
    int      us_map;
    int      us_copy;
} LibVADecodedFrame;

typedef void (*libva_log_fn)(const char *msg);

void              libva_decode_set_log(libva_log_fn fn);
LibVADecodeStatus libva_decode_startup(void);
void              libva_decode_shutdown(void);
const char       *libva_decode_get_device(void);
const char       *libva_decode_get_vendor(void);
const char       *libva_decode_get_last_error(void);
int               libva_decode_get_major(void);
int               libva_decode_get_minor(void);
int               libva_decode_supports(const char *encoding, const char *colorspace);

LibVADecodeStatus libva_decoder_create(LibVADecoder **out, const char *encoding,
                                       int width, int height, const char *colorspace);
void              libva_decoder_destroy(LibVADecoder *dec);
LibVADecodeStatus libva_decoder_decode(LibVADecoder *dec,
                                       const uint8_t *data, int data_len,
                                       LibVADecodedFrame *frame);

int               libva_decoder_get_width(LibVADecoder *dec);
int               libva_decoder_get_height(LibVADecoder *dec);
int               libva_decoder_get_last_status(LibVADecoder *dec);
const char       *libva_decoder_get_last_error(LibVADecoder *dec);
const char       *libva_decode_status_str(LibVADecodeStatus status);
const char       *libva_decode_format_str(LibVADecodeFormat format);

#ifdef __cplusplus
}
#endif

#endif /* XPRA_LIBVA_DECODE_H */
