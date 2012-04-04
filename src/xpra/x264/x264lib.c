/* Copyright (C) 2012 Serviware, Arthur Huillet <arthur dot huillet AT free dot fr>
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
#endif

#ifndef _WIN32
#include <x264.h>
#else
typedef void x264_t;
#define inline __inline
#endif

#include <libswscale/swscale.h>
#include <libavcodec/avcodec.h>
#include "x264lib.h"

struct x264lib_ctx {
	// Encoding
	x264_t *encoder;
	struct SwsContext *rgb2yuv;

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
	x264_param_t param;
	x264_param_default_preset(&param, "veryfast", "zerolatency");
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
#else
struct x264lib_ctx *init_encoder(int width, int height)
{
	return NULL;
}
#endif

void clean_encoder(struct x264lib_ctx *ctx)
{
	sws_freeContext(ctx->rgb2yuv);
}

struct x264lib_ctx *init_decoder(int width, int height)
{
	struct x264lib_ctx *ctx = malloc(sizeof(struct x264lib_ctx));
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
    avcodec_close(ctx->codec_ctx);
    av_free(ctx->codec_ctx);
	sws_freeContext(ctx->yuv2rgb);
}

#ifndef _WIN32
int compress_image(struct x264lib_ctx *ctx, const uint8_t *in, int stride, uint8_t **out, int *outsz)
{
	if (!ctx->encoder || !ctx->rgb2yuv)
		return 1;

	x264_picture_t pic_in, pic_out;
	x264_picture_alloc(&pic_in, X264_CSP_I420, ctx->width, ctx->height);

	/* Colorspace conversion (RGB -> I420) */
	sws_scale(ctx->rgb2yuv, &in, &stride, 0, ctx->height, pic_in.img.plane, pic_in.img.i_stride);

	/* Encoding */
	pic_in.i_pts = 1;

	x264_nal_t* nals;
	int i_nals;
	int frame_size = x264_encoder_encode(ctx->encoder, &nals, &i_nals, &pic_in, &pic_out);
	if (frame_size >= 0) {
		/* Do not free that! */
		*out = nals[0].p_payload;
		*outsz = frame_size;
	} else {
		fprintf(stderr, "Problem\n");
		x264_picture_clean(&pic_in);
		return 2;
	}
  
	x264_picture_clean(&pic_in);
	return 0;
}
#else
int compress_image(struct x264lib_ctx *ctx, const uint8_t *in, int stride, uint8_t **out, int *outsz)
{
	return 1;
}
#endif

int decompress_image(struct x264lib_ctx *ctx, uint8_t *in, int size, uint8_t **out, int *outsize, int *outstride)
{
    int got_picture;
	int len;
    AVFrame *picture;
    AVPacket avpkt;
	AVPicture pic;

	if (!ctx->yuv2rgb)
		return 1;

    av_init_packet(&avpkt);

	if (!ctx->codec_ctx || !ctx->codec)
		return 1;

    picture = avcodec_alloc_frame();

	avpkt.data = in;
	avpkt.size = size;
	
	len = avcodec_decode_video2(ctx->codec_ctx, picture, &got_picture, &avpkt);
	if (len < 0) {
		fprintf(stderr, "Error while decoding frame\n");
		*out = NULL;
		*outsize = 0;
		*outstride = 0;
		return 2;
	}

	avpicture_fill(&pic, malloc(ctx->height * ctx->width * 3), PIX_FMT_RGB24, ctx->width, ctx->height);

	/* Colorspace conversion (I420 -> RGB) */
	sws_scale(ctx->yuv2rgb, picture->data, picture->linesize, 0, ctx->height, pic.data, pic.linesize);
    
	av_free(picture);

	/* Output (must be freed!) */
	*out = pic.data[0];
	*outsize = pic.linesize[0] * ctx->height;
	*outstride = pic.linesize[0];

	//printf("After decoding, got %p, size %d, stride %d, size %d\n", pic.data[0], pic.linesize[0] * ctx->height, pic.linesize[0], pic.linesize[0]*ctx->height);
	return 0;
}
