/* This file is part of Xpra.
 * Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
 * Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
 * Parti is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#ifdef _WIN32
#include "stdint.h"
#include "inttypes.h"
#else
#include "stdint.h"
#endif
#include "vpx/vpx_image.h"

const char **get_supported_colorspaces();

/** Expose the VPX_CODEC_ABI_VERSION value */
int get_vpx_abi_version(void);

/** Opaque structure - "context". You must have a context to encode images of a given size */
struct vpx_context;

/** Create an encoding context for images of a given size.  */
struct vpx_context *init_encoder(int width, int height, const char *colorspace);

/** Create a decoding context for images of a given size. */
struct vpx_context *init_decoder(int width, int height, const char *colorspace);

/** Cleanup encoding context. Must be freed after calling this function. */
void clean_encoder(struct vpx_context *ctx);

/** Cleanup decoding context. Must be freed after calling this function. */
void clean_decoder(struct vpx_context *ctx);

/** Compress an image using the given context.
 @param pic_in: the input image, as returned by csc_image
 @param out: Will be set to point to the output data. This output buffer MUST NOT BE FREED and will be erased on the
 next call to compress_image.
 @param outsz: Output size
*/
int compress_image(struct vpx_context *ctx, uint8_t *input[3], int input_stride[3], uint8_t **out, int *outsz);

/** Decompress an image using the given context.
 @param in: Input buffer, format is H264.
 @param size: Input size.
 @param out: Will be filled to point to the output data in planar YUV420 format (3 planes). This data will be freed automatically upon next call to the decoder.
 @param outsize: Output size.
 @param outstride: Output strides (3 planes).
*/
int decompress_image(struct vpx_context *ctx, const uint8_t *in, int size, uint8_t *out[3], int outstride[3]);

/**
 * Retrieve the currently used colorspace (updated automatically by decoder).
 */
const char *get_colorspace(struct vpx_context *ctx);
