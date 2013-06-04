/* This file is part of Xpra.
 * Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
 * Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdint.h>
#include <inttypes.h>

#ifdef _WIN32
#define _STDINT_H
#endif
#if !defined(__APPLE__)
#include <malloc.h>
#endif

#include "csc_swscale.h"
#include <libswscale/swscale.h>

//not honoured on MS Windows:
#define MEMALIGN 1
//not honoured on OSX:
#define MEMALIGN_ALIGNMENT 32

/*
Speed results at 1024x1024 on Athlon II X4 620:

   BICUBIC | SWS_ACCURATE_RND 14ms/frame
   BICUBLIN | SWS_ACCURATE_RND 11ms/frame
   BICUBIC					   7ms/frame
   FAST_BILINEAR | SWS_ACCURATE_RND 9ms/frame
   FAST_BILINEAR               6ms/frame
   */

/* string format name <-> swscale flag correspondence */
typedef struct {
	const int flags;					/* swscale flags, ie: BICUBIC */
	const int speed;					/* ie: 50 */
	const char *description;			/* ie: "BICUBIC" */
} swscale_flag;
static swscale_flag swscale_flags[] = {
	{ SWS_BICUBIC | SWS_ACCURATE_RND,		30,		"BICUBIC | SWS_ACCURATE_RND" },
	{ SWS_BICUBLIN | SWS_ACCURATE_RND,		50,		"BICUBLIN | SWS_ACCURATE_RND" },
	{ SWS_FAST_BILINEAR | SWS_ACCURATE_RND,	70,		"FAST_BILINEAR | SWS_ACCURATE_RND" },
	{ SWS_BICUBIC,							80,		"BICUBIC" },
	{ SWS_BICUBLIN,							90,		"BICUBLIN" },
	{ SWS_FAST_BILINEAR,					100,	"FAST_BILINEAR" },
};
#define TOTAL_FLAGS (int)(sizeof(swscale_flags)/sizeof(swscale_flags[0]))


const swscale_flag *get_swscale_flags(int speed) {
	int i = 0;
	while (i<TOTAL_FLAGS && swscale_flags[i].speed<speed)
	{
		i++;
	}
	return &swscale_flags[i];
}




/** Context for csc_swscale_lib
 * convert colorspaces with libswscale
 */
struct csc_swscale_ctx {
	int src_width;
	int src_height;
	enum PixelFormat src_format;
	int dst_width;
	int dst_height;
	enum PixelFormat dst_format;
	const swscale_flag *flags;
	struct SwsContext *sws_ctx;
};



const char RGB[] = "RGB";
const char BGR[] = "BGR";
const char XRGB[] = "XRGB";
const char BGRX[] = "BGRX";
const char BGRA[] = "BGRA";
const char ARGB[] = "ARGB";
const char GBRP[] = "GBRP";
const char YUV420P[] = "YUV420P";
const char YUV422P[] = "YUV422P";
const char YUV444P[] = "YUV444P";


const char *COLORSPACES[] = {
		RGB, BGR,
		XRGB, BGRX,
		ARGB, BGRA,
		YUV420P, YUV422P, YUV444P,
#if LIBAVUTIL_VERSION_INT >= AV_VERSION_INT(51, 21, 0)
		GBRP,
#endif
		NULL,
	};

const char **get_supported_colorspaces(void)
{
	return COLORSPACES;
}


/* string format name <-> swscale format correspondence */
static const struct {
	enum PixelFormat sws_pixfmt; 
	float width_mult[3]; // width-to-stride multiplier for each plane
	float height_mult[3]; // height-to-plane-height multiplier for each plane
	const char *str;
} sws_formats[] = {
	{ PIX_FMT_RGB24,   { 3, 0, 0 },     { 1, 0, 0 },     RGB  },
	{ PIX_FMT_BGR24,   { 3, 0, 0 },     { 1, 0, 0 },     BGR  },
#if LIBAVUTIL_VERSION_INT >= AV_VERSION_INT(52, 14, 100)
	{ PIX_FMT_0RGB,    { 4, 0, 0 },     { 1, 0, 0 },     XRGB },
	{ PIX_FMT_BGR0,    { 4, 0, 0 },     { 1, 0, 0 },     BGRX },
#else
	{ PIX_FMT_ARGB,    { 4, 0, 0 },     { 1, 0, 0 },     XRGB },
	{ PIX_FMT_BGRA,    { 4, 0, 0 },     { 1, 0, 0 },     BGRX },
#endif
	{ PIX_FMT_ARGB,    { 4, 0, 0 },     { 1, 0, 0 },     ARGB },
	{ PIX_FMT_BGRA,    { 4, 0, 0 },     { 1, 0, 0 },     BGRA },
	{ PIX_FMT_YUV420P, { 1, 0.5, 0.5 }, { 1, 0.5, 0.5 }, YUV420P },
	{ PIX_FMT_YUV422P, { 1, 0.5, 0.5 }, { 1, 1, 1 },     YUV422P },
	{ PIX_FMT_YUV444P, { 1, 1, 1 },     { 1, 1, 1 },     YUV444P },
#if LIBAVUTIL_VERSION_INT >= AV_VERSION_INT(51, 21, 0)
	{ PIX_FMT_GBRP,    { 1, 1, 1 },		{ 1, 1, 1 },     GBRP },
#endif
};

#define TOTAL_FORMATS (int)(sizeof(sws_formats)/sizeof(sws_formats[0]))

static enum PixelFormat get_swscale_format(const char *str)
{
	int i;
	for (i = 0; i < TOTAL_FORMATS; i++) {
		if (!strcmp(sws_formats[i].str, str))
			return sws_formats[i].sws_pixfmt;
	}
	fprintf(stderr, "Unknown pixel format specified: %s\n", str);
	return PIX_FMT_NONE;
}

static int get_plane_dimensions(enum PixelFormat fmt, int width, int height, int stride[3], int plane_height[3])
{
	unsigned int i;
	int found = -1;
	for (i = 0; i < TOTAL_FORMATS; i++) {
		if (sws_formats[i].sws_pixfmt == fmt)
			break;
	}

	if (i == TOTAL_FORMATS) {
		fprintf(stderr, "Unknown pixel format specified: %d\n", fmt);
		return 1;
	}

	found = i;

#define ALIGN4(X) (((int)(X)+3)&~3)
	for (i = 0; i < 3; i++) {
		stride[i] = ALIGN4(width * sws_formats[found].width_mult[i]);
		plane_height[i] = height * sws_formats[found].height_mult[i];
	}

	return 0;
}

static void *xmemalign(size_t size)
{
#ifdef MEMALIGN
#ifdef _WIN32
	//_aligned_malloc and _aligned_free lead to a memleak
	//well done Microsoft, I didn't think you could screw up this badly
	//and thank you for wasting my time once again
	return malloc(size);
#elif defined(__APPLE__) || defined(__OSX__)
	//Crapple version: "all memory allocations are 16-byte aligned"
	//no choice, this is what you get
	return malloc(size);
#else
	//not WIN32 and not APPLE/OSX, assume POSIX:
	void *memptr = NULL;
	if (posix_memalign(&memptr, MEMALIGN_ALIGNMENT, size))
		return NULL;
	return memptr;
#endif
//MEMALIGN not set:
#else
	return malloc(size);
#endif
}

struct csc_swscale_ctx *init_csc(int src_width, int src_height, const char *src_format_str,
								 int dst_width, int dst_height, const char *dst_format_str, int speed)
{
	struct csc_swscale_ctx *ctx = malloc(sizeof(struct csc_swscale_ctx));
	if (!ctx)
		return NULL;

	ctx->src_width = src_width;
	ctx->src_height = src_height;
	ctx->src_format = get_swscale_format(src_format_str);
	ctx->dst_width = dst_width;
	ctx->dst_height = dst_height;
	ctx->dst_format = get_swscale_format(dst_format_str);
	ctx->flags = get_swscale_flags(speed);

	if (ctx->src_format == PIX_FMT_NONE || ctx->dst_format == PIX_FMT_NONE) {
		fprintf(stderr, "Invalid source or destination pixel format\n");
		goto err;
	}

	ctx->sws_ctx = sws_getContext(ctx->src_width, ctx->src_height, ctx->src_format, ctx->dst_width, ctx->dst_height, ctx->dst_format, ctx->flags->flags, NULL, NULL, NULL);

	if (!ctx->sws_ctx) {
		fprintf(stderr, "sws_getContext returned NULL\n");
		goto err;
	}

	return ctx;

err:
	free(ctx);
	return NULL;
}

void free_csc(struct csc_swscale_ctx *ctx)
{
	if (ctx && ctx->sws_ctx)
		sws_freeContext(ctx->sws_ctx);
}

void free_csc_image(uint8_t *buf[3])
{
	free(buf[0]);
	buf[0] = buf[1] = buf[2] = NULL;
}

int csc_image(struct csc_swscale_ctx *ctx, const uint8_t *in[3], const int in_stride[3], uint8_t *out[3], int out_stride[3])
{
	int out_height[3];
	int buffer_size;
	
	if (!ctx || !ctx->sws_ctx)
		return 1;

	// Compute output buffer size
	get_plane_dimensions(ctx->dst_format, ctx->dst_width, ctx->dst_height, out_stride, out_height);
	buffer_size = (out_stride[0] * out_height[0] + out_stride[1] * out_height[1] + out_stride[2] * out_height[2]);

	// Allocate output buffer
	out[0] = xmemalign(buffer_size);
	out[1] = out[0] + out_stride[0] * out_height[0];
	out[2] = out[1] + out_stride[1] * out_height[1];

	// Convert colorspace
	sws_scale(ctx->sws_ctx, in, in_stride, 0, ctx->src_height, out, out_stride);
	return 0;
}

const char *get_flags_description(struct csc_swscale_ctx *ctx) {
	return ctx->flags->description;
}
