/* This file is part of Xpra.
 * Copyright (C) 2012, 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
 * Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdint.h>
#include <inttypes.h>

#ifdef _WIN32
#define _STDINT_H
#define inline __inline
#endif

/** Opaque structure - "context". You must have a context to decode frames. */
struct dec_avcodec_ctx;

/** Create a decoding context for images of a given size. */
struct dec_avcodec_ctx *init_decoder(int width, int height, const char *colorspace);

/** Cleanup decoding context. */
void clean_decoder(struct dec_avcodec_ctx *);

/** Decompress an image using the given context.
 @param in: Input buffer, format is H264.
 @param size: Input size.
 @param out: Will be filled to point to the output data in planar YUV420 format (3 planes). This data will be freed automatically upon next call to the decoder.
 @param outstride: Output strides (3 planes).
*/
int decompress_image(struct dec_avcodec_ctx *ctx, const uint8_t *in, int size, uint8_t *out[3], int outstride[3]);

/** Retrieve video colorspace */
const char *get_colorspace(struct dec_avcodec_ctx *ctx);

