/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: Intel oneVPL HEVC 4:4:4 hardware decoder — C API header.
 * ABOUTME: Flat C interface wrapping MFXVideoDECODE for use from Cython. */

#ifndef VPL_DECODE_H
#define VPL_DECODE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct VPLDecoder VPLDecoder;

typedef enum {
    VPL_DEC_OK              =  0,
    VPL_DEC_NEED_MORE_INPUT =  1,
    VPL_DEC_STREAM_CHANGE   =  2,
    VPL_DEC_ERROR           = -1,
    VPL_DEC_NOT_AVAILABLE   = -2,
} VPLDecodeStatus;

/* Output pixel format reported by the decoder after header parse */
typedef enum {
    VPL_FMT_UNKNOWN = 0,
    VPL_FMT_AYUV    = 1,   /* 8-bit 4:4:4 packed (V,U,Y,A per pixel) */
    VPL_FMT_XYUV    = 2,   /* 8-bit 4:4:4 packed (V,U,Y,X per pixel) */
    VPL_FMT_Y410    = 3,   /* 10-bit 4:4:4 packed (U10:Y10:V10:A2)   */
} VPLPixelFormat;

typedef struct {
    uint8_t *data;          /* pointer to packed pixel data */
    int      stride;        /* bytes per row */
    int      width;
    int      height;
    int      full_range;
    VPLPixelFormat format;
    /* timing breakdown in microseconds */
    int      us_submit;     /* DecodeFrameAsync */
    int      us_sync;       /* SyncOperation (includes GPU decode) */
    int      us_map;        /* Map (GPU→CPU surface access) */
} VPLDecodedFrame;

/* Global init / shutdown (call once per process) */
VPLDecodeStatus vpl_decode_startup(void);
void            vpl_decode_shutdown(void);

/* Lifecycle.
   chroma444:  1 = request HEVC RExt 4:4:4, 0 = request HEVC Main/Main10 4:2:0.
   bit_depth:  8 or 10 (selects XYUV vs Y410 for 444, NV12 vs P010 for 420). */
VPLDecodeStatus vpl_decoder_create(VPLDecoder **out, int width, int height,
                                    int chroma444, int bit_depth);
void            vpl_decoder_destroy(VPLDecoder *dec);

/* Reconfigure an existing decoder for a new stream without destroying the
   session/loader. Equivalent to vpl_decoder_create's post-session state:
   session and loader stay alive, MFXVideoDECODE_Close runs, and the next
   decode triggers lazy_init (DecodeHeader + MFXVideoDECODE_Init). Saves
   MFXLoad + MFXCreateSession overhead on each reuse. */
VPLDecodeStatus vpl_decoder_reset(VPLDecoder *dec, int width, int height,
                                   int bit_depth);

/* Unmap and release the last decoded output surface, if any. Called
   before parking a decoder in the cache so the mapped surface does not
   stay pinned across idle time. */
void vpl_decoder_release_surface(VPLDecoder *dec);

/* Decode one compressed HEVC access unit.
   On VPL_DEC_OK, frame is populated; caller must copy before next call.
   On VPL_DEC_NEED_MORE_INPUT, frame is zeroed.
   On VPL_DEC_STREAM_CHANGE, dimensions changed; call vpl_decoder_get_output_size(). */
VPLDecodeStatus vpl_decoder_decode(VPLDecoder *dec,
                                    const uint8_t *data, int data_len,
                                    VPLDecodedFrame *frame);

/* Query current output dimensions */
void vpl_decoder_get_output_size(VPLDecoder *dec, int *width, int *height);

/* Info / diagnostics */
int             vpl_decoder_is_hardware(VPLDecoder *dec);
VPLPixelFormat  vpl_decoder_get_format(VPLDecoder *dec);
const char*     vpl_decode_status_str(VPLDecodeStatus status);
int             vpl_decoder_get_last_status(VPLDecoder *dec);
const char*     vpl_decoder_get_last_error(VPLDecoder *dec);

/* Logging callback — set before calling any other functions. */
typedef void (*vpl_log_fn)(const char *msg);
void            vpl_decode_set_log(vpl_log_fn fn);

#ifdef __cplusplus
}
#endif

#endif /* VPL_DECODE_H */
