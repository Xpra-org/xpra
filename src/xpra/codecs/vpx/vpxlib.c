/* This file is part of Xpra.
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
#include "vpx/vpx_codec.h"
#define fourcc    0x30385056
#define IVF_FILE_HDR_SZ  (32)

const char YUV420P[] = "YUV420P";

//Although those constants exist, they are not supported (yet?):
//"vpx_codec_encode: Invalid parameter"
//see:
//https://groups.google.com/a/webmproject.org/forum/?fromgroups#!msg/webm-discuss/f5Rmi-Cu63k/IXIzwVoXt_wJ
//"RGB is not supported.  You need to convert your source to YUV, and then compress that."
#define SUPPORT_RGB_MODES 0
#if SUPPORT_RGB_MODES
const char RGB[] = "RGB";
const char XRGB[] = "XRGB";
const char BGR[] = "BGR";
const char BGRA[] = "BGRA";
const char BGRX[] = "BGRX";
const char ARGB[] = "ARGB";
#endif

const char *COLORSPACES[] = {
	YUV420P,
#if SUPPORT_RGB_MODES
	RGB, BGR, BGRA, BGRX, ARGB,
#endif
	NULL
};

const char **get_supported_colorspaces(void)
{
	return COLORSPACES;
}


/* string format name <-> vpx format correspondence */
typedef struct {
	const vpx_img_fmt_t colorspace;
	const char *str;
} vpx_format;
static vpx_format vpx_formats[] = {
	{ VPX_IMG_FMT_I420,			YUV420P },
#if SUPPORT_RGB_MODES
	{ VPX_IMG_FMT_ARGB_LE,		BGRA },
	{ VPX_IMG_FMT_ARGB,			ARGB },
	{ VPX_IMG_FMT_RGB32_LE,		BGRX },
	{ VPX_IMG_FMT_BGR24,		BGR },
	{ VPX_IMG_FMT_RGB32,		XRGB },
	{ VPX_IMG_FMT_RGB24,		RGB },
#endif
};

#define TOTAL_FORMATS (int)(sizeof(vpx_formats)/sizeof(vpx_formats[0]))

static const vpx_img_fmt_t get_vpx_colorspace(const char *str)
{
	int i;
	for (i = 0; i < TOTAL_FORMATS; i++) {
		if (!strcmp(vpx_formats[i].str, str))
			return vpx_formats[i].colorspace;
	}
	fprintf(stderr, "Unknown pixel format specified: %s\n", str);
	return -1;
}
static const char *get_string_format(vpx_img_fmt_t pixfmt)
{
	int i;
	for (i = 0; i < TOTAL_FORMATS; i++) {
		if (vpx_formats[i].colorspace==pixfmt)
			return vpx_formats[i].str;
	}
	fprintf(stderr, "Unknown pixel format specified: %i\n", pixfmt);
	return "ERROR";
}


int get_vpx_abi_version(void)
{
	return VPX_CODEC_ABI_VERSION;
}

struct vpx_context {
	vpx_codec_ctx_t codec;
	int width;
	int height;
    vpx_img_fmt_t pixfmt;
} vpx_context;


static void codec_error(vpx_codec_ctx_t *ctx, const char *s)
{
	printf("%s: %s\n", s, vpx_codec_error(ctx));
	return;
	//const char *detail = vpx_codec_error_detail(ctx);
	//if (detail)
	//    printf("    %s\n", detail);
}

struct vpx_context *init_encoder(int width, int height, const char *colorspace)
{
	vpx_codec_enc_cfg_t cfg;
	vpx_img_fmt_t vpx_colorspace;
	struct vpx_context *ctx;
	vpx_codec_iface_t *codec_iface;

	vpx_colorspace = get_vpx_colorspace(colorspace);
	if (vpx_colorspace<0)
		return NULL;

	codec_iface = vpx_codec_vp8_cx();
	if (vpx_codec_enc_config_default(codec_iface, &cfg, 0))
		return NULL;

	cfg.rc_target_bitrate = width * height * cfg.rc_target_bitrate / cfg.g_w / cfg.g_h;
	cfg.g_w = width;
	cfg.g_h = height;
	cfg.g_error_resilient = 0;
	cfg.g_lag_in_frames = 0;
	cfg.rc_dropframe_thresh = 0;
	//cfg.rc_resize_allowed = 1;
	ctx = malloc(sizeof(struct vpx_context));
	if (ctx == NULL)
		return NULL;
	memset(ctx, 0, sizeof(struct vpx_context));
	if (vpx_codec_enc_init(&ctx->codec, codec_iface, &cfg, 0)) {
		codec_error(&ctx->codec, "vpx_codec_enc_init");
		free(ctx);
		return NULL;
	}
	ctx->width = width;
	ctx->height = height;
	ctx->pixfmt = vpx_colorspace;
	return ctx;
}

void clean_encoder(struct vpx_context *ctx)
{
	vpx_codec_destroy(&ctx->codec);
	free(ctx);
}

struct vpx_context *init_decoder(int width, int height, const char *colorspace)
{
	int flags = 0;
	int err = 0;
	vpx_codec_iface_t *codec_iface = NULL;
	struct vpx_context *ctx = malloc(sizeof(struct vpx_context));
	if (ctx == NULL)
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
	ctx->width = width;
	ctx->height = height;
	return ctx;
}

void clean_decoder(struct vpx_context *ctx)
{
	vpx_codec_destroy(&ctx->codec);
	free(ctx);
}

int compress_image(struct vpx_context *ctx, uint8_t *input[3], int input_stride[3], uint8_t **out, int *outsz)
{
	struct vpx_image image;
	const vpx_codec_cx_pkt_t *pkt;
	vpx_codec_iter_t iter = NULL;
	int frame_cnt = 0;
	int flags = 0;
	int i = 0;

	/* Encoding */
	memset(&image, 0, sizeof(struct vpx_image));
	image.w = ctx->width;
	image.h = ctx->height;
	image.fmt = ctx->pixfmt;
	image.planes[0] = input[0];
	image.planes[1] = input[1];
	image.planes[2] = input[2];
	image.stride[0] = input_stride[0];
	image.stride[1] = input_stride[1];
	image.stride[2] = input_stride[2];
	image.d_w = ctx->width;
	image.d_h = ctx->height;
	image.x_chroma_shift = 0;
	image.y_chroma_shift = 0;
	image.bps = 8;
	i = vpx_codec_encode(&ctx->codec, &image, frame_cnt, 1, flags, VPX_DL_REALTIME);
	if (i) {
		codec_error(&ctx->codec, "vpx_codec_encode");
		return i;
	}
	pkt = vpx_codec_get_cx_data(&ctx->codec, &iter);
	if (pkt->kind != VPX_CODEC_CX_FRAME_PKT) {
		return 1;
	}
	*out = pkt->data.frame.buf;
	*outsz = pkt->data.frame.sz;
	return 0;
}

int decompress_image(struct vpx_context *ctx, const uint8_t *in, int size, uint8_t *out[3], int outstride[3])
{
	vpx_image_t *img;
	int frame_sz = size;
	vpx_codec_iter_t iter = NULL;
	const uint8_t *frame = in;
	int i = 0;

	if (vpx_codec_decode(&ctx->codec, frame, frame_sz, NULL, 0)) {
		codec_error(&ctx->codec, "vpx_codec_decode");
		return -1;
	}
	img = vpx_codec_get_frame(&ctx->codec, &iter);
	if (img == NULL) {
		codec_error(&ctx->codec, "vpx_codec_get_frame");
		return -1;
	}

	for (i = 0; i < 3; i++) {
		out[i] = img->planes[i];
		outstride[i] = img->stride[i];
	}

    ctx->pixfmt = img->fmt;
	return 0;
}


const char *get_colorspace(struct vpx_context *ctx)
{
	return get_string_format(ctx->pixfmt);
}
