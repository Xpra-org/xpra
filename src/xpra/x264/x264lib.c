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
#include <stdint.h>
#include <inttypes.h>

#ifdef _WIN32
#define _STDINT_H
#endif
#if !defined(__APPLE__)
#include <malloc.h>
#endif

#include "x264lib.h"
#include <x264.h>
#include <libswscale/swscale.h>
#include <libavcodec/avcodec.h>
#include <libavutil/mem.h>


//not honoured on MS Windows:
#define MEMALIGN 1
//not honoured on OSX:
#define MEMALIGN_ALIGNMENT 32
//comment this out to turn off csc 422 and 444 colourspace modes
//(ie: when not supported by the library we build against)
#define SUPPORT_CSC_MODES 1


//beware that these macros may evaluate a or b twice!
//ie: do not use them for something like: MAX(i++, N)
#define MAX(a,b) ((a) > (b) ? a : b)
#define MIN(a,b) ((a) < (b) ? a : b)

struct x264lib_ctx {
	// Both
	int width;
	int height;
	int csc_format;				//PIX_FMT_YUV420P, X264_CSP_I422, PIX_FMT_YUV444P

	// Decoding
	AVCodec *codec;
	AVCodecContext *codec_ctx;
	AVFrame *frame;
	struct SwsContext *yuv2rgb;

	// Encoding
	x264_t *encoder;
	struct SwsContext *rgb2yuv;
	int use_swscale;

	int speed;					//percentage 0-100
	int quality;				//percentage 0-100
	int supports_csc_option;	//can we change colour sampling
	int encoding_preset;		//index in preset_names 0-9
	float x264_quality;			//rc.f_rf_constant (1 - 50)
	int colour_sampling;		//X264_CSP_I420, X264_CSP_I422 or X264_CSP_I444
	const char* profile;		//PROFILE_BASELINE, PROFILE_HIGH422 or PROFILE_HIGH444_PREDICTIVE
	const char* preset;			//x264_preset_names, see below:
	//x264_preset_names[] = {
	// "ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
	//"slow", "slower", "veryslow", "placebo", 0 }
	int csc_algo;

	const char* I420_profile;
	const char* I422_profile;
	const char* I444_profile;

	int I422_min;				//lowest point where we will continue to use 422
	int I444_min;				//lowest point where we will continue to use 444
	int I422_quality;			//threshold where we want to raise CSC to 422
	int I444_quality;			//threshold where we want to raise CSC to 444
	/*
	 * Explanation:
	 * We want to avoid changing CSC modes too often as this causes a full frame refresh.
	 * So the "quality" attributes define the thresholds where we want to raise the CSC quality,
	 * but once a CSC mode is set, we will only downgrade it if the quality then becomes
	 * lower than the "min" value. This prevents the yoyo effect.
	 * See get_x264_colour_sampling and can_keep_colour_sampling for the implementation.
	 * configure_encoder will ensure that the values respect these rules:
	 * 0 <= I422_min <= I422_quality <= 100
	 * 0 <= I444_min <= I444_quality <= 100
	 * I422_quality <= I444_quality
	 */
};

int get_encoder_pixel_format(struct x264lib_ctx *ctx) {
	return ctx->csc_format;
}
int get_encoder_quality(struct x264lib_ctx *ctx) {
	return ctx->quality;
}
int get_encoder_speed(struct x264lib_ctx *ctx) {
	return ctx->speed;
}

//Given a quality percentage (0 to 100),
//return the x264 quality constant to use
float get_x264_quality(int pct) {
	return	50.0f - (MIN(100, MAX(0, pct)) * 49.0f / 100.0f);
}

//Given a quality percentage (0 to 100),
//return the x264 colour sampling to use
//IMPORTANT: changes here must be reflected in get_profile_for_quality
// as not all pixel formats are supported by all profiles.
int get_x264_colour_sampling(struct x264lib_ctx *ctx, int pct)
{
#ifdef SUPPORT_CSC_MODES
	if (!ctx->supports_csc_option)
		return	X264_CSP_I420;
	if (pct < ctx->I422_quality)
		return	X264_CSP_I420;
	else if (pct < ctx->I444_quality)
		return	X264_CSP_I422;
	return	X264_CSP_I444;
#else
	return	X264_CSP_I420;
#endif
}
int can_keep_colour_sampling(struct x264lib_ctx *ctx, int pct)
{
#ifdef SUPPORT_CSC_MODES
	if (!ctx->supports_csc_option)
		return	ctx->colour_sampling==X264_CSP_I420;
	if (ctx->colour_sampling==X264_CSP_I444)
		return	pct>=ctx->I444_min;
	if (ctx->colour_sampling==X264_CSP_I422)
		return	pct>=ctx->I422_min && pct<=ctx->I444_quality;
	if (ctx->colour_sampling==X264_CSP_I420)
		return	pct<=ctx->I422_quality;
	return	-1;	//we should never get here!
#else
	//we can only use this one:
	return	ctx->colour_sampling==X264_CSP_I420;
#endif
}


//Given an x264 colour sampling constant,
//return the corresponding csc constant.
int get_csc_format_for_x264_format(int i_csp)
{
	if (i_csp == X264_CSP_I420)
		return	PIX_FMT_YUV420P;
#ifdef SUPPORT_CSC_MODES
	else if (i_csp == X264_CSP_I422)
		return	PIX_FMT_YUV422P;
	else if (i_csp == X264_CSP_I444)
		return	PIX_FMT_YUV444P;
#endif
	else {
		fprintf(stderr, "invalid pixel format: %i\n", i_csp);
		return -1;
	}
}

//Given a csc colour sampling constant,
//return our own generic csc constant (see codec_constants.py)
int get_pixel_format(int csc)
{
	if (csc == PIX_FMT_YUV420P || csc < 0)
		return 420;
	else if (csc == PIX_FMT_YUV422P)
		return 422;
	else if (csc == PIX_FMT_YUV444P)
		return 444;
	else
		return -1;
}

int get_csc_algo_for_quality(int initial_quality) {
	//always use the best quality as lower quality options
	//do not offer a significant speed improvement
	return SWS_BICUBLIN | SWS_ACCURATE_RND;
}

const int DEFAULT_INITIAL_QUALITY = 70;
const int DEFAULT_INITIAL_SPEED = 20;
const char I420[] = "I420";
const char I422[] = "I422";
const char I444[] = "I444";
const char PROFILE_BASELINE[] = "baseline";
const char PROFILE_MAIN[] = "main";
const char PROFILE_HIGH[] = "high";
const char PROFILE_HIGH10[] = "high10";
const char PROFILE_HIGH422[] = "high422";
const char PROFILE_HIGH444_PREDICTIVE[] = "high444";
const char *I420_PROFILES[7] = {PROFILE_BASELINE, PROFILE_MAIN, PROFILE_HIGH, PROFILE_HIGH10, PROFILE_HIGH422, PROFILE_HIGH444_PREDICTIVE, NULL};
const char *I422_PROFILES[3] = {PROFILE_HIGH422, PROFILE_HIGH444_PREDICTIVE, NULL};
const char *I444_PROFILES[2] = {PROFILE_HIGH444_PREDICTIVE, NULL};
const char *DEFAULT_I420_PROFILE = PROFILE_BASELINE;
const char *DEFAULT_I422_PROFILE = PROFILE_HIGH422;
const char *DEFAULT_I444_PROFILE = PROFILE_HIGH444_PREDICTIVE;
const int DEFAULT_I422_MIN_QUALITY = 80;
const int DEFAULT_I444_MIN_QUALITY = 90;

//Given a quality percentage (0 to 100)
//return the profile to use
//IMPORTANT: changes here must be reflected in get_x264_colour_sampling
// as not all pixel formats are supported by all profiles.
const char *get_profile_for_quality(struct x264lib_ctx *ctx, int pct) {
	if (pct < ctx->I422_quality)
		return	ctx->I420_profile;
	if (pct < ctx->I444_quality)
		return	ctx->I422_profile;
	return	ctx->I444_profile;
}

/**
 * Ensures that the profile given is valid and
 * returns a pointer to the const string for it.
 * (as we may pass temporary strings from python!)
 */
const char *get_valid_profile(const char* csc_mode, const char *profile, const char *profiles[], const char *default_profile)
{
	//printf("get_valid_profile(%s, %s, %p, %s)\n", csc_mode, profile, profiles, default_profile);
	int i = 0;
	if (profile==NULL)
		return	default_profile;
	while (profiles[i]!=NULL)
	{
		if (strcmp(profiles[i], profile)==0) {
			//printf("found valid %s profile: %s\n", csc_mode, profiles[i]);
			return profiles[i];
		}
		i++;
	}
	fprintf(stderr, "invalid %s profile specified: %s\n", csc_mode, profile);
	return default_profile;
}

struct SwsContext *init_encoder_csc(struct x264lib_ctx *ctx)
{
	if (ctx->rgb2yuv) {
		sws_freeContext(ctx->rgb2yuv);
		ctx->rgb2yuv = NULL;
	}
	return sws_getContext(ctx->width, ctx->height, PIX_FMT_RGB24, ctx->width, ctx->height, ctx->csc_format, ctx->csc_algo, NULL, NULL, NULL);
}

/**
 * Configure values that will not change during the lifetime of the encoder.
 */
void configure_encoder(struct x264lib_ctx *ctx, int width, int height,
		int initial_quality, int initial_speed,
		int supports_csc_option,
		int I422_quality, int I444_quality,
		int I422_min, int I444_min,
		char *i420_profile, char *i422_profile, char *i444_profile)
{
	//printf("configure_encoder(%p, %i, %i, %i, %i, %i, %i, %s, %s, %s)\n", ctx, width, height, initial_quality, supports_csc_option, I422_quality, I444_quality, i420_profile, i422_profile, i444_profile);
	ctx->use_swscale = 1;
	ctx->width = width;
	ctx->height = height;
	if (initial_speed >= 0)
		ctx->speed = initial_speed;
	else
		ctx->speed = DEFAULT_INITIAL_SPEED;
	if (initial_quality >= 0)
		ctx->quality = initial_quality;
	else
		ctx->quality = DEFAULT_INITIAL_QUALITY;
	//printf("configure_encoder: %ix%i q=%i\n", ctx->width, ctx->height, ctx->quality);
	ctx->supports_csc_option = supports_csc_option;
	if (I422_quality>=0 && I422_quality<=100)
		ctx->I422_quality = I422_quality;
	else
		ctx->I422_quality = DEFAULT_I422_MIN_QUALITY;
	if (I444_quality>=0 && I444_quality<=100 && I444_quality>=ctx->I422_quality)
		ctx->I444_quality = I444_quality;
	else
		ctx->I444_quality = MIN(100, MAX(DEFAULT_I444_MIN_QUALITY, ctx->I422_quality+10));
	//"min" values must be lower than the corresponding "quality" value:
	if (I422_min>=0 && I422_min<=100 && I422_min<=ctx->I422_quality)
		ctx->I422_min = I422_min;
	else
		ctx->I422_min = MAX(0, ctx->I422_quality-10);
	if (I444_min>=0 && I444_min<=100 && I444_min<=ctx->I444_quality)
		ctx->I444_min = I444_min;
	else
		ctx->I444_min = MAX(0, MIN(ctx->I422_min, ctx->I444_quality-10));
	//printf("configure_encoder: quality thresholds: I422=%i / I444=%i\n", ctx->I422_quality, ctx->I444_quality);
	//printf("configure_encoder: min quality: I422=%i / I444=%i\n", ctx->I422_min, ctx->I444_min);
	ctx->I420_profile = get_valid_profile(I420, i420_profile, I420_PROFILES, DEFAULT_I420_PROFILE);
	ctx->I422_profile = get_valid_profile(I422, i422_profile, I422_PROFILES, DEFAULT_I422_PROFILE);
	ctx->I444_profile = get_valid_profile(I444, i444_profile, I444_PROFILES, DEFAULT_I444_PROFILE);
	//printf("configure_encoder: profiles %s / %s / %s\n", ctx->I420_profile, ctx->I422_profile, ctx->I444_profile);
}

/**
 * Actually initialize the encoder.
 * This may be called more than once if required, ie:
 * - if the dimensions change,
 * - if the csc mode changes.
 */
void do_init_encoder(struct x264lib_ctx *ctx)
{
	x264_param_t param;
	ctx->colour_sampling = get_x264_colour_sampling(ctx, ctx->quality);
	ctx->x264_quality = get_x264_quality(ctx->quality);
	ctx->csc_format = get_csc_format_for_x264_format(ctx->colour_sampling);
	ctx->encoding_preset = 2;
	ctx->preset = x264_preset_names[ctx->encoding_preset];
	ctx->profile = get_profile_for_quality(ctx, ctx->quality);
	ctx->csc_algo = get_csc_algo_for_quality(ctx->quality);
	//printf("do_init_encoder(%p, %i, %i, %i, %i) colour_sampling=%i, initial x264_quality=%f, initial profile=%s\n", ctx, ctx->width, ctx->height, ctx->quality, ctx->supports_csc_option, ctx->colour_sampling, ctx->x264_quality, ctx->profile);
	printf("do_init_encoder(%p, %i, %i, %i, %i) colour_sampling=%i, initial x264_quality=%f, initial profile=%s\n", ctx, ctx->width, ctx->height, ctx->quality, ctx->supports_csc_option, ctx->colour_sampling, ctx->x264_quality, ctx->profile);

	x264_param_default_preset(&param, ctx->preset, "zerolatency");
	param.i_threads = 1;
	param.i_width = ctx->width;
	param.i_height = ctx->height;
	param.i_csp = ctx->colour_sampling;
	param.rc.f_rf_constant = ctx->x264_quality;
	param.i_log_level = X264_LOG_ERROR;
	param.i_keyint_max = 999999;	//we never lose frames or use seeking, so no need for regular I-frames
	param.i_keyint_min = 999999;	//we don't want IDR frames either
	param.b_intra_refresh = 0;		//no intra refresh
	param.b_open_gop = 1;			//allow open gop
	x264_param_apply_profile(&param, ctx->profile);
	ctx->encoder = x264_encoder_open(&param);
	if (ctx->use_swscale)
		ctx->rgb2yuv = init_encoder_csc(ctx);
}

struct x264lib_ctx *init_encoder(int width, int height,
		int initial_quality, int initial_speed,
		int supports_csc_option,
		int I422_quality, int I444_quality,
		int I422_min, int I444_min,
        char *i420_profile, char *i422_profile, char *i444_profile)
{
	struct x264lib_ctx *ctx = malloc(sizeof(struct x264lib_ctx));
	memset(ctx, 0, sizeof(struct x264lib_ctx));
	configure_encoder(ctx, width, height, \
					initial_quality, initial_speed, \
					supports_csc_option, \
					I422_quality, I444_quality, \
					I422_min, I444_min, \
					i420_profile, i422_profile, i444_profile);
	do_init_encoder(ctx);
	return ctx;
}


void clean_encoder(struct x264lib_ctx *ctx)
{
	do_clean_encoder(ctx);
	free(ctx);
}
void do_clean_encoder(struct x264lib_ctx *ctx)
{
	if (ctx->rgb2yuv) {
		sws_freeContext(ctx->rgb2yuv);
		ctx->rgb2yuv = NULL;
	}
	if (ctx->encoder) {
		x264_encoder_close(ctx->encoder);
		ctx->encoder = NULL;
	}
}


int init_decoder_context(struct x264lib_ctx *ctx, int width, int height, int use_swscale, int csc_fmt)
{
	if (csc_fmt<0)
		csc_fmt = PIX_FMT_YUV420P;
	ctx->use_swscale = use_swscale;
	ctx->width = width;
	ctx->height = height;
	ctx->csc_format = csc_fmt;
	ctx->csc_algo = get_csc_algo_for_quality(100);
	if (use_swscale)
		ctx->yuv2rgb = sws_getContext(ctx->width, ctx->height, ctx->csc_format, ctx->width, ctx->height, PIX_FMT_RGB24, ctx->csc_algo, NULL, NULL, NULL);

	avcodec_register_all();

	ctx->codec = avcodec_find_decoder(CODEC_ID_H264);
	if (!ctx->codec) {
		fprintf(stderr, "codec H264 not found!\n");
		return 1;
	}
	ctx->codec_ctx = avcodec_alloc_context3(ctx->codec);
	if (!ctx->codec_ctx) {
		fprintf(stderr, "failed to allocate codec context!\n");
		return 1;
	}
	ctx->codec_ctx->width = ctx->width;
	ctx->codec_ctx->height = ctx->height;
	ctx->codec_ctx->pix_fmt = csc_fmt;
	if (avcodec_open2(ctx->codec_ctx, ctx->codec, NULL) < 0) {
		fprintf(stderr, "could not open codec\n");
		return 1;
	}
	ctx->frame = avcodec_alloc_frame();
	if (!ctx->frame) {
	    fprintf(stderr, "could not allocate an AVFrame for decoding\n");
	    return 1;
	}
	return 0;
}
struct x264lib_ctx *init_decoder(int width, int height, int use_swscale, int csc_fmt)
{
	struct x264lib_ctx *ctx = malloc(sizeof(struct x264lib_ctx));
	if (ctx==NULL)
		return NULL;
	memset(ctx, 0, sizeof(struct x264lib_ctx));
	if (init_decoder_context(ctx, width, height, use_swscale, csc_fmt)) {
		clean_decoder(ctx);
		return NULL;
	}
	return ctx;
}

void do_clean_decoder(struct x264lib_ctx *ctx)
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
	if (ctx->yuv2rgb) {
		sws_freeContext(ctx->yuv2rgb);
		ctx->yuv2rgb = NULL;
	}
}
void clean_decoder(struct x264lib_ctx *ctx)
{
	do_clean_decoder(ctx);
	free(ctx);
}


x264_picture_t *csc_image_rgb2yuv(struct x264lib_ctx *ctx, const uint8_t *in, int stride)
{
	x264_picture_t *pic_in = NULL;
	if (!ctx->encoder || !ctx->rgb2yuv)
		return NULL;

	pic_in = malloc(sizeof(x264_picture_t));
	x264_picture_alloc(pic_in, ctx->colour_sampling, ctx->width, ctx->height);

	/* Colorspace conversion (RGB -> I4??) */
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
	x264_nal_t* nals = NULL;
	int i_nals = 0;
	x264_picture_t pic_out;
	int frame_size = 0;

	if (!ctx->encoder || !ctx->rgb2yuv) {
		free_csc_image(pic_in);
		*out = NULL;
		*outsz = 0;
		return 1;
	}

	/* Encoding */
	pic_in->i_pts = 1;
	frame_size = x264_encoder_encode(ctx->encoder, &nals, &i_nals, pic_in, &pic_out);
	// Unconditional cleanup:
	free_csc_image(pic_in);
	if (frame_size < 0) {
		fprintf(stderr, "Problem during x264_encoder_encode: frame_size is invalid!\n");
		*out = NULL;
		*outsz = 0;
		return 2;
	}
	/* Do not clean that! */
	*out = nals[0].p_payload;
	*outsz = frame_size;
	return 0;
}


int csc_image_yuv2rgb(struct x264lib_ctx *ctx, uint8_t *in[3], const int stride[3], uint8_t **out, int *outsz, int *outstride)
{
	AVPicture pic;

	if (!ctx->yuv2rgb)
		return 1;

	avpicture_fill(&pic, xmemalign(ctx->height * ctx->width * 3), PIX_FMT_RGB24, ctx->width, ctx->height);

	sws_scale(ctx->yuv2rgb, (const uint8_t * const*) in, stride, 0, ctx->height, pic.data, pic.linesize);

	/* Output (must be freed!) */
	*out = pic.data[0];
	*outsz = pic.linesize[0] * ctx->height;
	*outstride = pic.linesize[0];

	return 0;
}

void set_decoder_csc_format(struct x264lib_ctx *ctx, int csc_fmt)
{
	if (csc_fmt<0)
		csc_fmt = PIX_FMT_YUV420P;
	if (ctx->csc_format!=csc_fmt) {
		//we need to re-initialize with the new format:
		do_clean_decoder(ctx);
		if (init_decoder_context(ctx, ctx->width, ctx->height, ctx->use_swscale, csc_fmt)) {
			fprintf(stderr, "Failed to reconfigure decoder\n");
		}
	}
}

int decompress_image(struct x264lib_ctx *ctx, uint8_t *in, int size, uint8_t *(*out)[3], int (*outstride)[3])
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

	avpkt.data = in;
	avpkt.size = size;

	len = avcodec_decode_video2(ctx->codec_ctx, picture, &got_picture, &avpkt);
	if (len < 0) {
		fprintf(stderr, "Error while decoding frame\n");
		memset(out, 0, sizeof(*out));
		return 2;
	}

	for (i = 0; i < 3; i++) {
		(*out)[i] = picture->data[i];
		outsize += ctx->height * picture->linesize[i];
		(*outstride)[i] = picture->linesize[i];
	}

    if (outsize == 0) {
        fprintf(stderr, "Decoded image, size %d %d %d, ptr %p %p %p\n", (*outstride)[0] * ctx->height, (*outstride)[1]*ctx->height, (*outstride)[2]*ctx->height, picture->data[0], picture->data[1], picture->data[2]);
        return 3;
    }

	return 0;
}

/**
 * Change the speed of encoding (x264 preset).
 * @param percent: 100 for maximum ("ultrafast") with lowest compression, 0 for highest compression (slower)
 */
void set_encoding_speed(struct x264lib_ctx *ctx, int pct)
{
	x264_param_t param;
	int new_preset = 7-MAX(0, MIN(6, pct/16));
	x264_encoder_parameters(ctx->encoder, &param);
	ctx->speed = pct;
	if (new_preset==ctx->encoding_preset)
		return;
	//printf("set_encoding_speed(%i) old preset: %i=%s, new preset: %i=%s\n", pct, ctx->encoding_preset, x264_preset_names[ctx->encoding_preset], new_preset, x264_preset_names[new_preset]);
	ctx->encoding_preset = new_preset;
	//"tune" options: film, animation, grain, stillimage, psnr, ssim, fastdecode, zerolatency
	//Multiple tunings can be used if separated by a delimiter in ",./-+"
	//however multiple psy tunings cannot be used.
	//film, animation, grain, stillimage, psnr, and ssim are psy tunings.
	x264_param_default_preset(&param, x264_preset_names[ctx->encoding_preset], "zerolatency");
	param.rc.f_rf_constant = ctx->x264_quality;
	x264_param_apply_profile(&param, ctx->profile);
	x264_encoder_reconfig(ctx->encoder, &param);
}

/**
 * Change the quality of encoding (x264 f_rf_constant).
 * @param percent: 100 for best quality, 0 for lowest quality.
 */
void set_encoding_quality(struct x264lib_ctx *ctx, int pct)
{
	int old_csc_algo = ctx->csc_algo;
	float new_quality = get_x264_quality(pct);
	printf("set_encoding_quality(%i) new_quality=%f, can csc=%i\n", pct, new_quality, ctx->supports_csc_option);
	if (ctx->supports_csc_option) {
		if (!can_keep_colour_sampling(ctx, pct)) {
			int new_colour_sampling = get_x264_colour_sampling(ctx, pct);
			//printf("set_encoding_quality(%i) old colour_sampling=%i, new colour_sampling %i\n", pct, ctx->colour_sampling, new_colour_sampling);
			if (ctx->colour_sampling!=new_colour_sampling) {
				//pixel encoding has changed, we must re-init everything:
				do_clean_encoder(ctx);
				ctx->quality = pct;
				ctx->x264_quality = new_quality;
				do_init_encoder(ctx);
				//printf("new pixel format: %i / %i\n", get_encoder_pixel_format(ctx), get_pixel_format(get_encoder_pixel_format(ctx)));
				return;
			}
		}
	}
	if ((ctx->quality & ~0x1)!=(pct & ~0x1)) {
		//float old_quality = ctx->x264_quality;
		//printf("set_encoding_quality(%i) was %i, new x264 quality %f was %f\n", pct, ctx->quality, new_quality, old_quality);
		//only f_rf_constant was changed,
		//read new configuration is sufficient
		x264_param_t param;
		// Retrieve current parameters
		x264_encoder_parameters(ctx->encoder, &param);
		ctx->quality = pct;
		ctx->x264_quality = new_quality;
		param.rc.f_rf_constant = new_quality;
		x264_encoder_reconfig(ctx->encoder, &param);
	}
	ctx->csc_algo = get_csc_algo_for_quality(pct);
	if (old_csc_algo!=ctx->csc_algo) {
		ctx->rgb2yuv = init_encoder_csc(ctx);
	}
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
