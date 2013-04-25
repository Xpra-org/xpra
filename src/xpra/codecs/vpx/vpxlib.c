/* This file is part of Parti.
 * Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
 * Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
 * Parti is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>

#ifndef _WIN32
#include <stdint.h>
#include <unistd.h>
#else
#include "stdint.h"
#include "inttypes.h"
#define inline __inline
#endif

#define VPX_CODEC_DISABLE_COMPAT 1
#include "vpx/vpx_encoder.h"
#include "vpx/vp8cx.h"
#include "vpx/vpx_decoder.h"
#include "vpx/vp8dx.h"
#include "vpxlib.h"
#include "vpx/vpx_image.h"
#define fourcc    0x30385056
#define IVF_FILE_HDR_SZ  (32)
#include <libswscale/swscale.h>

struct vpx_context {
	vpx_codec_ctx_t codec;
	int use_swscale;
	struct SwsContext *rgb2yuv;
	struct SwsContext *yuv2rgb;
	int width;
	int height;
} vpx_context;


static void codec_error(vpx_codec_ctx_t *ctx, const char *s) {
    printf("%s: %s\n", s, vpx_codec_error(ctx));
    return;
	//const char *detail = vpx_codec_error_detail(ctx);
    //if (detail)
    //    printf("    %s\n", detail);
}

struct vpx_context *init_encoder(int width, int height)
{
	vpx_codec_enc_cfg_t  cfg;
	struct vpx_context *ctx;
	vpx_codec_iface_t *codec_iface = vpx_codec_vp8_cx();
	if (vpx_codec_enc_config_default(codec_iface, &cfg, 0))
		return	NULL;
	cfg.rc_target_bitrate = width * height * cfg.rc_target_bitrate / cfg.g_w / cfg.g_h;
	cfg.g_w = width;
	cfg.g_h = height;
	ctx = malloc(sizeof(struct vpx_context));
	if (ctx==NULL)
		return NULL;
	memset(ctx, 0, sizeof(struct vpx_context));
	if (vpx_codec_enc_init(&ctx->codec, codec_iface, &cfg, 0)) {
		codec_error(&ctx->codec, "vpx_codec_enc_init");
		free(ctx);
		return NULL;
	}
	ctx->use_swscale = 1;
	ctx->width = width;
	ctx->height = height;
	if (ctx->use_swscale)
		ctx->rgb2yuv = sws_getContext(width, height, PIX_FMT_RGB24, width, height, PIX_FMT_YUV420P, SWS_FAST_BILINEAR, NULL, NULL, NULL);
	return ctx;
}

void clean_encoder(struct vpx_context *ctx)
{
	if (ctx->rgb2yuv)
		sws_freeContext(ctx->rgb2yuv);
	vpx_codec_destroy(&ctx->codec);
	free(ctx);
}

struct vpx_context *init_decoder(int width, int height, int use_swscale)
{
	int flags = 0;
	int err = 0;
	vpx_codec_iface_t *codec_iface = NULL;
	struct vpx_context *ctx = malloc(sizeof(struct vpx_context));
	if (ctx==NULL)
		return NULL;
	codec_iface = vpx_codec_vp8_dx();
	memset(ctx, 0, sizeof(struct vpx_context));
	err = vpx_codec_dec_init(&ctx->codec, codec_iface, NULL, flags);
	if (err) {
		codec_error(&ctx->codec, "vpx_codec_dec_init");
		printf("vpx_codec_dec_init(..) failed with error %d\n", err);
		free(ctx);
		return NULL;
	}
	ctx->use_swscale = use_swscale;
	ctx->width = width;
	ctx->height = height;
	if (ctx->use_swscale)
		ctx->yuv2rgb = sws_getContext(width, height, PIX_FMT_YUV420P, width, height, PIX_FMT_RGB24, SWS_FAST_BILINEAR, NULL, NULL, NULL);
	return	ctx;
}

void clean_decoder(struct vpx_context *ctx)
{
	if (ctx->yuv2rgb)
		sws_freeContext(ctx->yuv2rgb);
	vpx_codec_destroy(&ctx->codec);
	free(ctx);
}

vpx_image_t* csc_image_rgb2yuv(struct vpx_context *ctx, const uint8_t *in, int stride)
{
	vpx_image_t *image = malloc(sizeof(vpx_image_t));
	if (image==NULL)
		return NULL;
	if (!vpx_img_alloc(image, VPX_IMG_FMT_I420, ctx->width, ctx->height, 1)) {
		printf("Failed to allocate image %dx%d\n", ctx->width, ctx->height);
		return NULL;
	}
	/* Colorspace conversion (RGB -> I420) */
	sws_scale(ctx->rgb2yuv, &in, &stride, 0, ctx->height, image->planes, image->stride);
	image->w = ctx->width;
	image->h = ctx->height;
	image->d_w = ctx->width;
	image->d_h = ctx->height;
	return image;
}

int compress_image(struct vpx_context *ctx, vpx_image_t *image, uint8_t **out, int *outsz)
{
	const vpx_codec_cx_pkt_t *pkt;
	vpx_codec_iter_t iter = NULL;
	int frame_cnt = 0;
	int flags = 0;
	int i = 0;

	/* Encoding */
	image->x_chroma_shift = 0;
	image->y_chroma_shift = 0;
	image->bps = 8;
	i = vpx_codec_encode(&ctx->codec, image, frame_cnt, 1, flags, VPX_DL_REALTIME);
	if (i) {
		codec_error(&ctx->codec, "vpx_codec_encode");
		vpx_img_free(image);
		return i;
	}
	pkt = vpx_codec_get_cx_data(&ctx->codec, &iter);
	if (pkt->kind!=VPX_CODEC_CX_FRAME_PKT) {
		vpx_img_free(image);
		return 1;
	}
	*out = pkt->data.frame.buf;
	*outsz = pkt->data.frame.sz;
	vpx_img_free(image);
	return 0;
}

int csc_image_yuv2rgb(struct vpx_context *ctx, uint8_t *in[3], const int stride[3], uint8_t **out, int *outsz, int *outstride)
{
	uint8_t *dst[4] = { xmemalign(ctx->height * ctx->width * 3), NULL, NULL, NULL };
	int dststride[4] = { ctx->width * 3, 0, 0, 0 };

	if (!ctx->yuv2rgb)
		return 1;

	sws_scale(ctx->yuv2rgb, (const uint8_t * const*) in, stride, 0, ctx->height, dst, dststride);

	/* Output (must be freed!) */
	*out = dst[0];
	*outsz = dststride[0] * ctx->height;
	*outstride = dststride[0];

	return 0;
}

int decompress_image(struct vpx_context *ctx, uint8_t *in, int size, uint8_t *(*out)[3], int *outsize, int (*outstride)[3])
{
	vpx_image_t      *img;
	int frame_sz = size;
	vpx_codec_iter_t  iter = NULL;
	uint8_t* frame = in;
	int i = 0;

	if (vpx_codec_decode(&ctx->codec, frame, frame_sz, NULL, 0)) {
		codec_error(&ctx->codec, "vpx_codec_decode");
		return -1;
	}
	img = vpx_codec_get_frame(&ctx->codec, &iter);
	if (img==NULL) {
		codec_error(&ctx->codec, "vpx_codec_get_frame");
		return -1;
	}

	*outsize = 0;
	for (i = 0; i < 3; i++) {
		(*out)[i] = img->planes[i];
		(*outstride)[i] = img->stride[i];
		*outsize += img->stride[i] * img->h;
	}

	return 0;
}


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
