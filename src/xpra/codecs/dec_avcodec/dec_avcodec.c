/* This file is part of Xpra.
 * Copyright (C) 2012, 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
 * Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <stdint.h>
#include <inttypes.h>

#ifdef _WIN32
#define _STDINT_H
#endif

#include "dec_avcodec.h"
#include <libavcodec/avcodec.h>
#include <libavutil/mem.h>

/** Context for dec_avcodec_lib
 * decode video with libavcodec
 */
struct dec_avcodec_ctx{
	int width;
	int height;
	AVCodec *codec;
	AVCodecContext *codec_ctx;
	AVFrame *frame;
	enum PixelFormat pixfmt;		//may get updated by swscale!
};


const char YUV420P[] = "YUV420P";
const char YUV422P[] = "YUV422P";
const char YUV444P[] = "YUV444P";
const char ARGB[] = "ARGB";
const char BGRA[] = "BGRA";
const char BGRX[] = "BGRX";
const char XRGB[] = "XRGB";
const char GBRP[] = "GBRP";

const char *COLORSPACES[] = {
	YUV420P,
	YUV422P,
	YUV444P,
	XRGB,
	BGRX,
	ARGB,
	BGRA,
#if LIBAVUTIL_VERSION_INT >= AV_VERSION_INT(51, 21, 0)
	GBRP,
#endif
	NULL
};

const char **get_supported_colorspaces(void)
{
	return COLORSPACES;
}

/* string format name <-> swscale format correspondance */
static const struct {
	enum PixelFormat pixfmt;
	const char *str;
} sws_formats[] = {
	{ PIX_FMT_YUV420P, "YUV420P" },
	{ PIX_FMT_YUV422P, "YUV422P" },
	{ PIX_FMT_YUV444P, "YUV444P" },
	{ PIX_FMT_RGB24,   "RGB"  },
#if LIBAVUTIL_VERSION_INT >= AV_VERSION_INT(52, 14, 100)
	{ PIX_FMT_0RGB,    "XRGB" },
	{ PIX_FMT_BGR0,    "BGRX" },
#else
	{ PIX_FMT_ARGB,    "XRGB" },
	{ PIX_FMT_BGRA,    "BGRX" },
#endif
	{ PIX_FMT_ARGB,    "ARGB" },
	{ PIX_FMT_BGRA,    "BGRA" },
#if LIBAVUTIL_VERSION_INT >= AV_VERSION_INT(51, 21, 0)
	{ PIX_FMT_GBRP,    "GBRP" },
#endif
};

#define TOTAL_FORMATS (int)(sizeof(sws_formats)/sizeof(sws_formats[0]))

static enum PixelFormat get_swscale_format(const char *str)
{
	int i;
	for (i = 0; i < TOTAL_FORMATS; i++) {
		//fprintf(stderr, "testing %s, %i\n", sws_formats[i].str, sws_formats[i].pixfmt);
		if (!strcmp(sws_formats[i].str, str))
			return sws_formats[i].pixfmt;
	}
	fprintf(stderr, "Cannot find PixelFormat: unknown name specified: %s\n", str);
	return PIX_FMT_NONE;
}

static const char *get_string_format(enum PixelFormat pixfmt)
{
	//BEWARE: XRGB/BGRX and ARGB/BGRA may get mapped to the same
	//underlying swscale constant.. so you may not get the string you expect!
	int i;
	for (i = 0; i < TOTAL_FORMATS; i++) {
		if (sws_formats[i].pixfmt == pixfmt)
			return sws_formats[i].str;
	}
	fprintf(stderr, "Cannot find pixel format string: unknown enum specified: %d\n", pixfmt);
	return "unknown";
}

struct dec_avcodec_ctx *init_decoder(int width, int height, const char *colorspace)
{
	struct dec_avcodec_ctx *ctx;
	enum PixelFormat pix_fmt = get_swscale_format(colorspace);
	if (pix_fmt==PIX_FMT_NONE)
		return NULL;
	//fprintf(stderr, "found PixelFormat(%s)=%i=%s\n", colorspace, pix_fmt, get_string_format(pix_fmt));

	ctx = malloc(sizeof(struct dec_avcodec_ctx));
	if (!ctx)
		return NULL;
	memset(ctx, 0, sizeof(struct dec_avcodec_ctx));

	ctx->width = width;
	ctx->height = height;
	ctx->pixfmt = pix_fmt;

	avcodec_register_all();

	ctx->codec = avcodec_find_decoder(CODEC_ID_H264);
	if (!ctx->codec) {
		fprintf(stderr, "codec H264 not found!\n");
		return NULL;
	}
	//from here on, we have to call clean_decoder():
	ctx->codec_ctx = avcodec_alloc_context3(ctx->codec);
	if (!ctx->codec_ctx) {
		fprintf(stderr, "failed to allocate codec context!\n");
		goto err;
	}
	ctx->codec_ctx->width = ctx->width;
	ctx->codec_ctx->height = ctx->height;
	ctx->codec_ctx->pix_fmt = pix_fmt;
	if (avcodec_open2(ctx->codec_ctx, ctx->codec, NULL) < 0) {
		fprintf(stderr, "could not open codec\n");
		goto err;
	}
	ctx->frame = avcodec_alloc_frame();
	if (!ctx->frame) {
		fprintf(stderr, "could not allocate an AVFrame for decoding\n");
		goto err;
	}
	return ctx;

err:
	clean_decoder(ctx);
	return NULL;
}

void clean_decoder(struct dec_avcodec_ctx *ctx)
{
	if (ctx->frame) {
		avcodec_free_frame(&ctx->frame);
		ctx->frame = NULL;
	}
	if (ctx->codec_ctx) {
		avcodec_close(ctx->codec_ctx);
		av_free(ctx->codec_ctx);
		ctx->codec_ctx = NULL;
	}
}

int decompress_image(struct dec_avcodec_ctx *ctx, const uint8_t *in, int size, uint8_t *out[3], int outstride[3])
{
	int got_picture;
	int len;
	int i;
	int outsize = 0;
	AVFrame *picture = ctx->frame;
	AVPacket avpkt;

	av_init_packet(&avpkt);

	if (!ctx->codec_ctx || !ctx->codec)
		return 1;

	avcodec_get_frame_defaults(picture);

	avpkt.data = (uint8_t *)in;
	avpkt.size = size;

	len = avcodec_decode_video2(ctx->codec_ctx, picture, &got_picture, &avpkt);
	if (len < 0) {
		fprintf(stderr, "Error while decoding frame\n");
		out[0] = out[1] = out[2] = NULL;
		return 2;
	}

	for (i = 0; i < 3; i++) {
		out[i] = picture->data[i];
		outsize += ctx->height * picture->linesize[i];
		outstride[i] = picture->linesize[i];
	}

	if (outsize == 0) {
		fprintf(stderr, "Decoded image, size %d %d %d, ptr %p %p %p\n",
			outstride[0] * ctx->height,
			outstride[1] * ctx->height,
			outstride[2] * ctx->height, picture->data[0],
			picture->data[1], picture->data[2]);
		return 3;
	}

	// Update actual colorspace from what avcodec tells us
	if (ctx->pixfmt!=picture->format) {
		//fprintf(stderr, "decompress_image actual output format updated from %s to %s\n",
		//				get_string_format(ctx->pixfmt), get_string_format(picture->format));
		ctx->pixfmt = picture->format;
	}
	return 0;
}

const char *get_colorspace(struct dec_avcodec_ctx *ctx)
{
	return get_string_format(ctx->pixfmt);
}
