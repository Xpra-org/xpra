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

/** Opaque structure - "context". You must have a context to convert frames. */
struct csc_swscale_ctx;

const char **get_supported_colorspaces(void);

const char *get_flags_description(struct csc_swscale_ctx *ctx);

/** Create a CSC context */
struct csc_swscale_ctx *init_csc(int src_width, int src_height, const char *src_format_str,
								 int dst_width, int dst_height, const char *dst_format_str, int speed);

/** Free a CSC context */
void free_csc(struct csc_swscale_ctx *ctx);

/**
 * Colorspace conversion.
 * @param in: array of pointers to the planes of input frame
 * @param in_stride: array of input plane strides
 * @param out: array that will be set to point to the planes of output frame
 * @param out_stride: array that will be set to the output strides
 * @return 0 if OK, non zero on error
 * Note: you must call free_csc_image() with the out[] array as argument when done
 */
int csc_image(struct csc_swscale_ctx *ctx, const uint8_t *in[3], const int in_stride[3], uint8_t *out[3], int out_stride[3]);

/**
 * Free data output by csc_image()
 */
void free_csc_image(uint8_t *buf[3]);
