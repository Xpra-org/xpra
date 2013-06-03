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

#include <x264.h>

/** Opaque structure - "context". You must have a context to encode frames. */
struct enc_x264_ctx;

const char **get_supported_colorspaces(void);

/** Expose the X264_BUILD value */
int get_x264_build_no(void);

const char * get_profile(struct enc_x264_ctx *ctx);
const char * get_preset(struct enc_x264_ctx *ctx);

/** Expose current quality setting */
int get_encoder_quality(struct enc_x264_ctx *ctx);

/** Expose current speed setting */
int get_encoder_speed(struct enc_x264_ctx *ctx);

/** Returns the pixel format using our own generic codec_constants */
int get_pixel_format(int csc);

/** Cleanup encoding context. Also frees the memory. */
void clean_encoder(struct enc_x264_ctx *);

/** Compress an image using the given context.
 @param in: the input image, as returned by csc_image_rgb2yuv. It will be freed along with its container x264_picture_t automatically.
 @param out: Will be set to point to the output data. This output buffer MUST NOT BE FREED and will be erased on the
 next call to compress_image.
 @param outsz: Output size
 @param quality_override: Desired quality setting (0 to 100), -1 to use current settings.
*/
int compress_image(struct enc_x264_ctx *ctx, uint8_t *in[3], int in_stride[3], uint8_t **out, int *outsz);

/**
 * Change the speed of encoding (x264 preset).
 * @param percent: 100 for maximum ("ultrafast") with lowest compression, 0 for highest compression (slower)
 */
void set_encoding_speed(struct enc_x264_ctx *ctx, int pct);

/**
 * Change the quality of encoding (x264 f_rf_constant).
 * @param percent: 100 for maximum quality, 0 for lowest quality
 */
void set_encoding_quality(struct enc_x264_ctx *ctx, int pct);

/** Retrieve list (NULL-terminated) of supported colorspace strings. */
const char **get_supported_colorspaces(void);

/** Create an encoding context for images of a given size.  */
struct enc_x264_ctx *init_encoder(int width, int height,
		const char *colorspace, const char *profile,
		int initial_quality, int initial_speed);
