/* This file is part of Parti.
 * Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
 * Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
 * Parti is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>

//not honoured on MS Windows:
#define MEMALIGN 1
//not honoured on OSX:
#define MEMALIGN_ALIGNMENT 32

#ifdef _WIN32
#include <malloc.h>
#include "stdint.h"
#include "inttypes.h"
#else
#include <stdint.h>
#include <unistd.h>
#endif

#ifdef _WIN32
typedef void x264_t;
#define inline __inline
#else
#include <x264.h>
#endif

#include <libswscale/swscale.h>
#include <libavcodec/avcodec.h>
#include "x264lib.h"


struct x264lib_ctx {
	// Encoding
	x264_t *encoder;
	struct SwsContext *rgb2yuv;
	int encoding_preset;

	// Decoding
	AVCodec *codec;
	AVCodecContext *codec_ctx;
	struct SwsContext *yuv2rgb;

	// Both
	int width;
	int height;
};

#ifndef _WIN32
struct x264lib_ctx *init_encoder(int width, int height)
{
	struct x264lib_ctx *ctx = malloc(sizeof(struct x264lib_ctx));
	ctx->encoding_preset = 2;
	x264_param_t param;
	x264_param_default_preset(&param, x264_preset_names[ctx->encoding_preset], "zerolatency");
	param.i_threads = 1;
	param.i_width = width;
	param.i_height = height;
	param.i_csp = X264_CSP_I420;
	param.i_log_level = 0;
	x264_param_apply_profile(&param, "baseline");
	ctx->encoder = x264_encoder_open(&param);
	ctx->width = width;
	ctx->height = height;
	ctx->rgb2yuv = sws_getContext(ctx->width, ctx->height, PIX_FMT_RGB24, ctx->width, ctx->height, PIX_FMT_YUV420P, SWS_POINT, NULL, NULL, NULL);

	return ctx;
}

void clean_encoder(struct x264lib_ctx *ctx)
{
	if (ctx->rgb2yuv)
		sws_freeContext(ctx->rgb2yuv);
	if (ctx->encoder)
		x264_encoder_close(ctx->encoder);
}

#else
struct x264lib_ctx *init_encoder(int width, int height)
{
	return NULL;
}

void clean_encoder(struct x264lib_ctx *ctx)
{
	return;
}
#endif

struct x264lib_ctx *init_decoder(int width, int height)
{
	struct x264lib_ctx *ctx = malloc(sizeof(struct x264lib_ctx));
	memset(ctx, 0, sizeof(struct x264lib_ctx));
	ctx->width = width;
	ctx->height = height;
	ctx->yuv2rgb = sws_getContext(ctx->width, ctx->height, PIX_FMT_YUV420P, ctx->width, ctx->height, PIX_FMT_RGB24, SWS_POINT | SWS_ACCURATE_RND, NULL, NULL, NULL);

	avcodec_register_all();

	ctx->codec = avcodec_find_decoder(CODEC_ID_H264);
	if (!ctx->codec) {
		fprintf(stderr, "codec not found\n");
		free(ctx);
		return NULL;
	}
	ctx->codec_ctx = avcodec_alloc_context3(ctx->codec);
	ctx->codec_ctx->width = ctx->width;
	ctx->codec_ctx->height = ctx->height;
	ctx->codec_ctx->pix_fmt = PIX_FMT_YUV420P;
	if (avcodec_open(ctx->codec_ctx, ctx->codec) < 0) {
		fprintf(stderr, "could not open codec\n");
		free(ctx);
		return NULL;
	}

	return ctx;
}

void clean_decoder(struct x264lib_ctx *ctx)
{
	if (ctx->codec_ctx)
		avcodec_close(ctx->codec_ctx);
		av_free(ctx->codec_ctx);
	if (ctx->yuv2rgb)
		sws_freeContext(ctx->yuv2rgb);
}

#ifndef _WIN32
x264_picture_t *csc_image_rgb2yuv(struct x264lib_ctx *ctx, const uint8_t *in, int stride)
{
	if (!ctx->encoder || !ctx->rgb2yuv)
		return NULL;

	x264_picture_t *pic_in = malloc(sizeof(x264_picture_t));
	x264_picture_alloc(pic_in, X264_CSP_I420, ctx->width, ctx->height);

	/* Colorspace conversion (RGB -> I420) */
	sws_scale(ctx->rgb2yuv, &in, &stride, 0, ctx->height, pic_in->img.plane, pic_in->img.i_stride);
	return pic_in;
}

static void free_csc_image(x264_picture_t *image)
{
	x264_picture_clean(image);
	free(image);
}

int compress_image(struct x264lib_ctx *ctx, x264_picture_t *pic_in, uint8_t **out, int *outsz)
{
	if (!ctx->encoder || !ctx->rgb2yuv) {
		free_csc_image(pic_in);
		*out = NULL;
		*outsz = 0;
		return 1;
	}
	x264_picture_t pic_out;

	/* Encoding */
	pic_in->i_pts = 1;

	x264_nal_t* nals;
	int i_nals;
	int frame_size = x264_encoder_encode(ctx->encoder, &nals, &i_nals, pic_in, &pic_out);
	if (frame_size < 0) {
		fprintf(stderr, "Problem during x264_encoder_encode: frame_size is invalid!\n");
		free_csc_image(pic_in);
		*out = NULL;
		*outsz = 0;
		return 2;
	}
	/* Do not clean that! */
	*out = nals[0].p_payload;
	*outsz = frame_size;
	free_csc_image(pic_in);
	return 0;
}
#else
x264_picture_t* csc_image_rgb2yuv(struct x264lib_ctx *ctx, const uint8_t *in, int stride) 
{
	return	NULL;
}
int compress_image(struct x264lib_ctx *ctx, x264_picture_t *pic_in, uint8_t **out, int *outsz)
{
	return 1;
}
#endif

int csc_image_yuv2rgb(struct x264lib_ctx *ctx, uint8_t *in[3], const int stride[3], uint8_t **out, int *outsz, int *outstride)
{
	AVPicture pic;
	
	if (!ctx->yuv2rgb)
		return 1;
	
	avpicture_fill(&pic, malloc(ctx->height * ctx->width * 3), PIX_FMT_RGB24, ctx->width, ctx->height);

	sws_scale(ctx->yuv2rgb, (const uint8_t * const*) in, stride, 0, ctx->height, pic.data, pic.linesize);
	
	/* Output (must be freed!) */
	*out = pic.data[0];
	*outsz = pic.linesize[0] * ctx->height;
	*outstride = pic.linesize[0];

	return 0;
}

int decompress_image(struct x264lib_ctx *ctx, uint8_t *in, int size, uint8_t *(*out)[3], int *outsize, int (*outstride)[3])
{
	int got_picture;
	int len;
	int i;
	AVFrame picture;
	AVPacket avpkt;

	av_init_packet(&avpkt);

	if (!ctx->codec_ctx || !ctx->codec)
		return 1;

	avcodec_get_frame_defaults(&picture);

	avpkt.data = in;
	avpkt.size = size;
	
	len = avcodec_decode_video2(ctx->codec_ctx, &picture, &got_picture, &avpkt);
	if (len < 0) {
		fprintf(stderr, "Error while decoding frame\n");
		memset(out, 0, sizeof(*out));
		return 2;
	}

	for (i = 0; i < 3; i++) {
		(*out)[i] = picture.data[i];
		*outsize += ctx->height * picture.linesize[i];
		(*outstride)[i] = picture.linesize[i];
	}

    if (*outsize == 0) {
        fprintf(stderr, "Decoded image, size %d %d %d, ptr %p %p %p\n", (*outstride)[0] * ctx->height, (*outstride)[1]*ctx->height, (*outstride)[2]*ctx->height, picture.data[0], picture.data[1], picture.data[2]);
        return 3;
    }

	return 0;
}

/**
 * Change the speed of encoding (x264 preset).
 * @param increase: increase encoding speed (decrease preset) by this value. Negative values decrease encoding speed.
 */
#ifndef _WIN32
void change_encoding_speed(struct x264lib_ctx *ctx, int increase)
{
	x264_param_t param;
	x264_encoder_parameters(ctx->encoder, &param);
	int new_preset = max(0, min(5, ctx->encoding_preset-increase));
	if (new_preset==ctx->encoding_preset)
		return
	ctx->encoding_preset = new_preset;
	x264_param_default_preset(&param, x264_preset_names[ctx->encoding_preset], "zerolatency");
	//printf("Setting encoding preset %s %d\n", x264_preset_names[ctx->encoding_preset], ctx->encoding_preset);
	x264_param_apply_profile(&param, "baseline");
	x264_encoder_reconfig(ctx->encoder, &param);
}
#else
void change_encoding_speed(struct x264lib_ctx *ctx, int increase)
{
	;
}
#endif

void* xmemalign(size_t size)
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
	void* memptr=NULL;
	if (posix_memalign(&memptr, MEMALIGN_ALIGNMENT, size))
		return	NULL;
	return	memptr;
#endif
//MEMALIGN not set:
#else
	return	malloc(size);
#endif
}

void xmemfree(void *ptr)
{
	free(ptr);
}
