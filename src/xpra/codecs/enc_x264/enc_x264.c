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

#include "enc_x264.h"
#include <x264.h>

#define MAX(a,b) ((a) > (b) ? a : b)
#define MIN(a,b) ((a) < (b) ? a : b)

/** Context for enc_x264_lib
 * encode video with x264
 */
struct enc_x264_ctx {
	int width;
	int height;
	x264_t *x264_ctx;
	int speed;					//percentage 0-100
	int quality;				//percentage 0-100
	int encoding_preset;		//index in x264_preset_names
	int color_sampling;			//X264_CSP_I420, X264_CSP_I422 or X264_CSP_I444
	const char *colorspace;
	const char *profile;
};

int get_x264_build_no(void)
{
	return X264_BUILD;
}

int get_encoder_quality(struct enc_x264_ctx *ctx)
{
	return ctx->quality;
}

int get_encoder_speed(struct enc_x264_ctx *ctx)
{
	return ctx->speed;
}

/** Translate a quality percentage (0 to 100)
 * into an x264 constant quality factor (51 to 0)
 */
float get_x264_quality(int pct)
{
	return 50.0f - (MIN(100, MAX(0, pct)) * 49.0f / 100.0f);
}

/**
 * Translate a speed percentage (0 to 100)
 * into an x264 preset.
 * @param percent:	100 for maximum ("ultrafast") with lowest compression,
 *					0 for highest compression ("slower")
 */
int get_preset_for_speed(int speed)
{
	if (speed > 99)
		// only allow "ultrafast" if pct > 99
		return 0;
	return 7 - MAX(0, MIN(6, speed / 15));
}


const char PROFILE_BASELINE[] = "baseline";
const char PROFILE_MAIN[] = "main";
const char PROFILE_HIGH[] = "high";
const char PROFILE_HIGH10[] = "high10";
const char PROFILE_HIGH422[] = "high422";
const char PROFILE_HIGH444_PREDICTIVE[] = "high444";
const char *I420_PROFILES[7] = {PROFILE_BASELINE, PROFILE_MAIN, PROFILE_HIGH, PROFILE_HIGH10, PROFILE_HIGH422, PROFILE_HIGH444_PREDICTIVE, NULL};
const char *I422_PROFILES[3] = {PROFILE_HIGH422, PROFILE_HIGH444_PREDICTIVE, NULL};
const char *I444_PROFILES[2] = {PROFILE_HIGH444_PREDICTIVE, NULL};
const char *RGB_PROFILES[2] = {PROFILE_HIGH444_PREDICTIVE, NULL};


const char *DEFAULT_I420_PROFILE = PROFILE_BASELINE;
const char *DEFAULT_I422_PROFILE = PROFILE_HIGH422;
const char *DEFAULT_I444_PROFILE = PROFILE_HIGH444_PREDICTIVE;
const char *DEFAULT_RGB_PROFILE = PROFILE_HIGH444_PREDICTIVE;

const char YUV420P[] = "YUV420P";
const char YUV422P[] = "YUV422P";
const char YUV444P[] = "YUV444P";
const char RGB[] = "RGB";
const char BGR[] = "BGR";
const char BGRA[] = "BGRA";
const char BGRX[] = "BGRX";

const char *COLORSPACES[] = {YUV420P,
#if X264_BUILD >= 118
	YUV422P,
#endif
#if X264_BUILD >= 116
	YUV444P,
#endif
#if X264_BUILD >= 117
	RGB,
	BGR,
	BGRA,
	BGRX,
#endif
	NULL
};

const char **get_supported_colorspaces(void)
{
	return COLORSPACES;
}

/* string format name <-> x264 format correspondence */
typedef struct {
	const int colorspace;				/* x264 enum */
	const char *str;					/* ie: RGBA or YUV420P */
	const char *default_profile;		/* the default profile to use for this colorspace */
	const char **profiles;				/* list of valid profiles for this colorspace */
} x264_format;
static x264_format x264_formats[] = {
	{ X264_CSP_I420,		YUV420P,		PROFILE_HIGH,				I420_PROFILES },
#if X264_BUILD >= 118
	{ X264_CSP_I422,		YUV422P,		PROFILE_HIGH422,			I422_PROFILES },
#endif
#if X264_BUILD >= 116
	{ X264_CSP_I444,		YUV444P,		PROFILE_HIGH444_PREDICTIVE,	I444_PROFILES },
#endif
#if X264_BUILD >= 117
	{ X264_CSP_BGR,			BGR,			PROFILE_HIGH444_PREDICTIVE,	RGB_PROFILES },
	{ X264_CSP_BGRA,		BGRA,			PROFILE_HIGH444_PREDICTIVE,	RGB_PROFILES },
	{ X264_CSP_BGRA,		BGRX,			PROFILE_HIGH444_PREDICTIVE,	RGB_PROFILES },
	{ X264_CSP_RGB,			RGB,			PROFILE_HIGH444_PREDICTIVE,	RGB_PROFILES },
#endif
};

#define TOTAL_FORMATS (int)(sizeof(x264_formats)/sizeof(x264_formats[0]))

static const x264_format *get_x264_format(const char *str)
{
	int i;
	for (i = 0; i < TOTAL_FORMATS; i++) {
		if (!strcmp(x264_formats[i].str, str))
			return &x264_formats[i];
	}
	fprintf(stderr, "Unknown pixel format specified: %s\n", str);
	return NULL;
}

/**
 * Ensures that the profile given is valid and
 * returns a pointer to the const string for it.
 * (as we may pass temporary strings from python!)
 */
const char *get_valid_profile(const char *csc_mode, const char *profile, const char *profiles[], const char *default_profile)
{
	int i = 0;
	if (profile == NULL || strlen(profile)==0)
		return default_profile;
	while (profiles[i] != NULL) {
		if (strcmp(profiles[i], profile) == 0) {
			//printf("found valid %s profile: %s\n", csc_mode, profiles[i]);
			return profiles[i];
		}
		i++;
	}
	fprintf(stderr, "invalid %s profile specified: %s, using: %s\n", csc_mode, profile, default_profile);
	return default_profile;
}


const char * get_profile(struct enc_x264_ctx *ctx)
{
	return ctx->profile;
}
const char * get_preset(struct enc_x264_ctx *ctx)
{
	return x264_preset_names[ctx->encoding_preset];
}


/**
 * Set context parameters
 */
static int configure_encoder(struct enc_x264_ctx *ctx,
		int width, int height, const char *colorspace, const char *profile,
		int initial_quality, int initial_speed)
{
	const x264_format *format;
	format = get_x264_format(colorspace);
	if (format==NULL) {
		fprintf(stderr, "invalid colorspace specified: %s\n", colorspace);
		return 1;
	}
	ctx->width = width;
	ctx->height = height;
	ctx->speed = initial_speed;
	ctx->quality = initial_quality;
	ctx->encoding_preset = get_preset_for_speed(ctx->speed);
	ctx->colorspace = format->str;
	ctx->color_sampling = format->colorspace;
	ctx->profile = get_valid_profile(colorspace, profile, format->profiles, format->default_profile);
	if (ctx->profile==NULL) {
		fprintf(stderr, "cannot find a valid profile for %s\n", colorspace);
		return 1;
	}
	//fprintf(stderr, "enc_x264 configure_encoder: using colorspace=%s, color_sampling=%i, profile=%s\n",
	//		ctx->colorspace, ctx->color_sampling, ctx->profile);
	return 0;
}

/**
 * Actually initialize the encoder.
 * This may be called more than once if required, ie:
 * - if the dimensions change
 */
void do_init_encoder(struct enc_x264_ctx *ctx)
{
	x264_param_t param;
	x264_param_default_preset(&param, x264_preset_names[ctx->encoding_preset], "zerolatency");
	param.i_threads = 1;
	param.i_width = ctx->width;
	param.i_height = ctx->height;
	param.i_csp = ctx->color_sampling;
	param.rc.f_rf_constant = get_x264_quality(ctx->quality);
	param.i_log_level = X264_LOG_ERROR;
	param.i_keyint_max = 999999;	//we never lose frames or use seeking, so no need for regular I-frames
	param.i_keyint_min = 999999;	//we don't want IDR frames either
	param.b_intra_refresh = 0;		//no intra refresh
	param.b_open_gop = 1;			//allow open gop
	x264_param_apply_profile(&param, ctx->profile);
	ctx->x264_ctx = x264_encoder_open(&param);
	//fprintf(stderr, "enc_x264 do_init_encoder got context=%p\n", ctx->x264_ctx);
}

struct enc_x264_ctx *init_encoder(int width, int height,
				const char *colorspace, const char *profile,
				int initial_quality, int initial_speed)
{
	struct enc_x264_ctx *ctx = malloc(sizeof(struct enc_x264_ctx));
	if (ctx == NULL)
		return NULL;
	memset(ctx, 0, sizeof(struct enc_x264_ctx));
	if (configure_encoder(ctx,
			  width, height, colorspace, profile,
			  initial_quality, initial_speed)!=0) {
		clean_encoder(ctx);
		return NULL;
	}
	do_init_encoder(ctx);
	return ctx;
}

void do_clean_encoder(struct enc_x264_ctx *ctx)
{
	if (ctx->x264_ctx) {
		x264_encoder_close(ctx->x264_ctx);
		ctx->x264_ctx = NULL;
	}
}

void clean_encoder(struct enc_x264_ctx *ctx)
{
	do_clean_encoder(ctx);
	free(ctx);
}


int compress_image(struct enc_x264_ctx *ctx, uint8_t *in[3], int in_stride[3], uint8_t **out, int *outsz)
{
	x264_nal_t *nals = NULL;
	int i_nals = 0;
	x264_picture_t pic_out;
	x264_picture_t pic_in;
	int frame_size = 0;

	memset(&pic_out, 0, sizeof(x264_picture_t));
	memset(&pic_in, 0, sizeof(x264_picture_t));
	pic_in.img.i_csp = ctx->color_sampling;
	pic_in.img.i_plane = 3;
	pic_in.img.i_stride[0] = in_stride[0];
	pic_in.img.i_stride[1] = in_stride[1];
	pic_in.img.i_stride[2] = in_stride[2];
	pic_in.img.i_stride[3] = 0;
	pic_in.img.plane[0] = in[0];
	pic_in.img.plane[1] = in[1];
	pic_in.img.plane[2] = in[2];
	pic_in.img.plane[3] = NULL;

	/* Encoding */
	pic_in.i_pts = 1;
	frame_size = x264_encoder_encode(ctx->x264_ctx, &nals, &i_nals, &pic_in, &pic_out);
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

/**
 * Change the speed of encoding (x264 preset).
 * @see get_preset_for_speed
 */
void set_encoding_speed(struct enc_x264_ctx *ctx, int pct)
{
	x264_param_t param;
	int new_preset = get_preset_for_speed(pct);
	ctx->speed = pct;
	if (new_preset == ctx->encoding_preset)
		return;
	x264_encoder_parameters(ctx->x264_ctx, &param);
	ctx->encoding_preset = new_preset;
	x264_param_default_preset(&param, x264_preset_names[ctx->encoding_preset], "zerolatency");
	param.rc.f_rf_constant = get_x264_quality(ctx->quality);
	x264_param_apply_profile(&param, ctx->profile);
	x264_encoder_reconfig(ctx->x264_ctx, &param);
}

/**
 * Change the quality of encoding
 * @param percent: 100 for best quality, 0 for lowest quality.
 */
void set_encoding_quality(struct enc_x264_ctx *ctx, int pct)
{
	if ((ctx->quality & ~0x1) != (pct & ~0x1)) {
		//float old_quality = ctx->x264_quality;
		//only f_rf_constant was changed,
		//read new configuration is sufficient
		x264_param_t param;
		// Retrieve current parameters
		x264_encoder_parameters(ctx->x264_ctx, &param);
		ctx->quality = pct;
		param.rc.f_rf_constant = get_x264_quality(pct);
		x264_encoder_reconfig(ctx->x264_ctx, &param);
	}
}
