/* Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
   Copyright (C) 2012 Serviware, Arthur Huillet <arthur dot huillet AT free dot fr>
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
#define enc_interface (vpx_codec_vp8_cx())
#define dec_interface (vpx_codec_vp8_dx())
#define fourcc    0x30385056
#define IVF_FILE_HDR_SZ  (32)
#include <libswscale/swscale.h>

struct vpx_context {
	vpx_codec_ctx_t codec;
	struct SwsContext *rgb2yuv;
	struct SwsContext *yuv2rgb;
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
	if (vpx_codec_enc_config_default(enc_interface, &cfg, 0))
		return	NULL;
	cfg.rc_target_bitrate = width * height * cfg.rc_target_bitrate / cfg.g_w / cfg.g_h;
	cfg.g_w = width;
	cfg.g_h = height;
	ctx = malloc(sizeof(struct vpx_context));
	if (vpx_codec_enc_init(&ctx->codec, enc_interface, &cfg, 0)) {
		codec_error(&ctx->codec, "vpx_codec_enc_init");
		free(ctx);
		return NULL;
	}
	ctx->rgb2yuv = sws_getContext(width, height, PIX_FMT_RGB24, width, height, PIX_FMT_YUV420P, SWS_FAST_BILINEAR, NULL, NULL, NULL);
	return ctx;
}

void clean_encoder(struct vpx_context *ctx)
{
	vpx_codec_destroy(&ctx->codec);
	free(ctx);
}

struct vpx_context *init_decoder(int width, int height)
{
	struct vpx_context *ctx = malloc(sizeof(struct vpx_context));
	int              flags = 0;
	//printf("Using %s\n", vpx_codec_iface_name(dec_interface));
	int i = vpx_codec_dec_init(&ctx->codec, dec_interface, NULL, flags);
	if (i) {
		codec_error(&ctx->codec, "vpx_codec_dec_init");
		printf("vpx_codec_dec_init(..) failed with error %d\n", i);
		free(ctx);
		return NULL;
	}
	ctx->yuv2rgb = sws_getContext(width, height, PIX_FMT_YUV420P, width, height, PIX_FMT_RGB24, SWS_FAST_BILINEAR, NULL, NULL, NULL);
	return	ctx;
}

void clean_decoder(struct vpx_context *ctx)
{
	vpx_codec_destroy(&ctx->codec);
	free(ctx);
}

int compress_image(struct vpx_context *ctx, uint8_t *in, int w, int h, int stride, uint8_t **out, int *outsz)
{
	vpx_image_t image;
	const vpx_codec_cx_pkt_t *pkt;
	vpx_codec_iter_t iter = NULL;
	int frame_cnt = 0;
	int flags = 0;
	int i = 0;
	if (!vpx_img_alloc(&image, VPX_IMG_FMT_I420, w, h, 1)) {
		printf("Failed to allocate image %dx%d", w, h);
		return -1;
	}
	image.w = w;
	image.h = h;
	image.d_w = w;
	image.d_h = h;
	image.x_chroma_shift = 0;
	image.y_chroma_shift = 0;
	image.bps = 8;

	/* Colorspace conversion (RGB -> I420) */
	sws_scale(ctx->rgb2yuv, &in, &stride, 0, h, image.planes, image.stride);
	/* Encoding */
	i = vpx_codec_encode(&ctx->codec, &image, frame_cnt, 1, flags, VPX_DL_REALTIME);
	if (i) {
		codec_error(&ctx->codec, "vpx_codec_encode");
		return i;
	}
	pkt = vpx_codec_get_cx_data(&ctx->codec, &iter);
	if (pkt->kind!=VPX_CODEC_CX_FRAME_PKT)
		return 1;
	*out = pkt->data.frame.buf;
	*outsz = pkt->data.frame.sz;
	return 0;
}

int decompress_image(struct vpx_context *ctx, uint8_t *in, int size, uint8_t **out, int *outsize, int *outstride)
{
	vpx_image_t      *img;
	int frame_sz = size;
	vpx_codec_iter_t  iter = NULL;
	uint8_t* frame = in;
	int outstrides[4];
	uint8_t* outs[4];
	int stride = 0;
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
	for (i=0; i<4; i++)
		stride += img->stride[i];
	*outsize = stride * img->h;

	*out = malloc(*outsize);
	for (i=0; i<4; i++) {
		outstrides[i] = img->w*3;
		outs[i] = *out;
	}
	sws_scale(ctx->yuv2rgb, img->planes, img->stride, 0, img->h, outs, outstrides);
	stride = 0;
	for (i=0; i<4; i++)
		stride += img->stride[i];
	*outstride = stride;
	return 0;
}
