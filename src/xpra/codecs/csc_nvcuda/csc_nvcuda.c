/* Copyright (C) 2012-2013 Arthur Huillet <arthur dot huillet AT free dot fr>
   */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

#include <cuda.h>
#include <cuda_runtime.h>
#include <npp.h>

#ifndef _WIN32
#include <stdint.h>
#include <unistd.h>
#else
#include "stdint.h"
#include "inttypes.h"
#endif

#include "csc_nvcuda.h"

#define USE_TIMER
#ifdef USE_TIMER
#include "../timer.h"
#else
#define timer_display_and_reset(X,Y)
#endif

static int cuda_device = -1;
static int cuda_initialized = 0;
static CUcontext *cuda_context;

enum colorspace {
	UNKNOWN=-1,
	RGB = 0,
	RGBA,
	BGR,
	BGRA,
	YUV420P,
	YUV422P,
	YUV444P,
};

struct csc_nvcuda_ctx {
	int width;
	int height;
	enum colorspace src_colorspace;
	enum colorspace dst_colorspace;
};

static const struct {
	enum colorspace cspace;
	const char *name;
} colorspaces[] = {
		{ RGB,     "RGB"     },
		{ RGBA,    "RGBA"    },
		{ BGR,     "BGR"     },
		{ BGRA,	   "BGRX"    },
		{ YUV420P, "YUV420P" },
		{ YUV422P, "YUV422P" },
		{ YUV444P, "YUV444P" },
};
/*	{ PIX_FMT_RGB24,   { 3, 0, 0 },     { 1, 0, 0 },     "RGB"  },
	{ PIX_FMT_0RGB,    { 4, 0, 0 },     { 1, 0, 0 },     "XRGB" },
	{ PIX_FMT_BGR0,    { 4, 0, 0 },     { 1, 0, 0 },     "BGRX" },
	{ PIX_FMT_ARGB,    { 4, 0, 0 },     { 1, 0, 0 },     "ARGB" },
	{ PIX_FMT_BGRA,    { 4, 0, 0 },     { 1, 0, 0 },     "BGRA" },
	{ PIX_FMT_YUV420P, { 1, 0.5, 0.5 }, { 1, 0.5, 0.5 }, "YUV420P" },
	{ PIX_FMT_YUV422P, { 1, 0.5, 0.5 }, { 1, 1, 1 },     "YUV422P" },
	{ PIX_FMT_YUV444P, { 1, 1, 1 },     { 1, 1, 1 },     "YUV444P" }
*/


/* Representing the functions in a single table would be quite difficult.
   Instead, we use several tables to represent the Npp functions to be called.
   */
typedef NppStatus (*packed_to_subsampled_planar_func) (const Npp8u * pSrc, int nSrcStep, Npp8u * pDst[3], int rDstStep[3], NppiSize oSizeROI);
typedef NppStatus (*packed_to_planar_func) (const Npp8u * pSrc, int nSrcStep, Npp8u * pDst[3], int DstStep, NppiSize oSizeROI);

static packed_to_planar_func NPP_dst_YUV444P[] = {
	[RGB] = nppiRGBToYCbCr_8u_C3P3R,
	[RGBA] = nppiRGBToYCbCr_8u_AC4P3R,
	[BGR] = NULL, // not present in NPP, need nppiSwapChannels first
	[BGRA] = NULL, // same as above
};

static packed_to_subsampled_planar_func NPP_dst_YUV422P[] = {
	[RGB] = nppiRGBToYCbCr422_8u_C3P3R,
	[RGBA] = NULL, //WTF?
	[BGR] = nppiBGRToYCbCr422_8u_C3P3R,
	[BGRA] = nppiBGRToYCbCr422_8u_AC4P3R,
};

static packed_to_subsampled_planar_func NPP_dst_YUV420P[] = {
	[RGB] =  nppiRGBToYCbCr420_8u_C3P3R,
	[RGBA] =  NULL, //WTF?
	[BGR] =  nppiBGRToYCbCr420_8u_C3P3R,
	[BGRA] =  nppiBGRToYCbCr420_8u_AC4P3R,
};

#define ARRAY_SIZE(X) (int)(sizeof(X)/sizeof(X[0]))
static enum colorspace get_colorspace_by_name(const char *str) 
{
	int i;
	if (!str)
		return UNKNOWN;

	for (i = 0; i < ARRAY_SIZE(colorspaces); i++) {
		if (!strcmp(str, colorspaces[i].name))
			return colorspaces[i].cspace;
	}

	fprintf(stderr, "Colorspace %s not supported.\n", str);
	return UNKNOWN;
}

/* Retrieve the conversion function for a un-subsampled planar destination. 
 This cannot be unified because the NPP signatures are different from the other variants.*/
packed_to_planar_func get_conversion_function_444(enum colorspace src, enum colorspace dst)
{
	if (dst != YUV444P)
		return NULL;

	if (src >= ARRAY_SIZE(NPP_dst_YUV444P)) {
		fprintf(stderr, "Source colorspace %d not supported for YUV444P destination\n", src);
		return NULL;
	}

	return NPP_dst_YUV444P[src];
}

/* Retrieve the conversion function for a subsampled planar destination. */
packed_to_subsampled_planar_func get_conversion_function_subsampled(enum colorspace src, enum colorspace dst)
{
#define get_func(ARR) do { \
		if (src >= ARRAY_SIZE(ARR)) \
			return NULL; \
		return ARR[src];	\
		} while (0)
	if (dst == YUV420P) {
		get_func(NPP_dst_YUV420P);
	} else if (dst == YUV422P) {
		get_func(NPP_dst_YUV422P);
	} else {
		fprintf(stderr, "Destination colorspace %d not supported as subsampled dest.\n", dst);
		return NULL;
	}
}

static void _cuda_report_error(int line, const char *fmt, ...)
{
	fprintf(stderr, "Cuda error in %s:%d: ", __FILE__, line);
	va_list ap;
	va_start(ap, fmt);
	vfprintf(stderr, fmt, ap);
	va_end(ap);
	fprintf(stderr, " - %s\n", cudaGetErrorString(cudaGetLastError()));
}

#define cuda_err(fmt, ...) _cuda_report_error(__LINE__, fmt, ##__VA_ARGS__)

static int init_cuda(struct csc_nvcuda_ctx *ctx)
{
	int cuda_count = 0;
	char PCI_id[25];
	struct cudaDeviceProp prop;

#ifdef USE_TIMER
	struct my_timer t = timer_create();
#endif
	if (cudaGetDeviceCount(&cuda_count)) {
		fprintf(stderr, "No CUDA devices available.\n");
	}

	timer_display_and_reset(&t, "getdevicecount");
	int i;
	for (i = 0; i < cuda_count; i++) {
		cudaSetDevice(i);
		timer_display_and_reset(&t, "setdevice");

		// Retrieve device properties
		if (cudaGetDeviceProperties(&prop, i)) {
			cuda_err("Error retrieving Cuda device %d properties, skipping", i);
			continue;
		}
		timer_display_and_reset(&t, "getprops");

		// Check if device is able to map host memory
		if (!prop.canMapHostMemory) {
			cuda_err("Device %d cannot map host memory, skipping", i);
			continue;
		}
	
		// Tell CUDA we want to map host memory
		if(cudaSetDeviceFlags(cudaDeviceMapHost)) {
			cuda_err("Unable to set cudaDeviceMapHost device flag");
			return 1;
		}
		timer_display_and_reset(&t, "setflags");

		// All good - select this device! 
		break;
	}

	if (i == cuda_count) {
		fprintf(stderr, "No suitable CUDA devices available.\n");
		return 1;
	}

	// Select this device
	cuda_device = i;

	const NppLibraryVersion *lib_version = nppGetLibVersion();

	// Report status
		// This call initializes the device for real, instead of it being done later when converting frames
	cudaDeviceGetPCIBusId(PCI_id, sizeof(PCI_id), cuda_device);
	printf("Using CUDA device %s at %s, NPP version %d.%d.%d\n", nppGetGpuName(), PCI_id, lib_version->major, lib_version->minor, lib_version->build);

	if (cuInit(0)) {
		fprintf(stderr, "cuInit failed\n");
	}

	printf("curren = %p\n", cuCtxGetCurrent(cuda_context));
	printf("Cuda context ptr%p\n", cuda_context);
	cuda_initialized = 1;
	return 0;
}

struct csc_nvcuda_ctx *init_csc(int width, int height, const char *src_format_str, const char *dst_format_str)
{
	struct csc_nvcuda_ctx *ctx = malloc(sizeof(struct csc_nvcuda_ctx));
	if (!ctx)
		return NULL;
	
	ctx->width = width;
	ctx->height = height;
	ctx->src_colorspace = get_colorspace_by_name(src_format_str);
	ctx->dst_colorspace = get_colorspace_by_name(dst_format_str);

	// Check if we have a conversion function for src->dst
	void *func;
	if (ctx->dst_colorspace == YUV444P) {
		func = get_conversion_function_444(ctx->src_colorspace, ctx->dst_colorspace);
	} else {
		func = get_conversion_function_subsampled(ctx->src_colorspace, ctx->dst_colorspace);
	}
	if (!func) {
		fprintf(stderr, "Colorspace conversion with source %s and destination %s is not supported by csc_nvcuda.\n", src_format_str, dst_format_str);
		goto err;
	}

	// Initialize Cuda (once in the application's lifetime)			
	if (!cuda_initialized) {
		if (init_cuda(ctx)) {
			goto err;
		}
	}

	return ctx;
err:
	free(ctx);
	return NULL;
}

int csc_image(struct csc_nvcuda_ctx *ctx, const uint8_t *in[3], const int stride[3], uint8_t *out[3], int out_stride[3])
{
	if (!ctx)
		return 1;

	int pinned_input_buffer = 1;
	int pinned_output_buffer = 1;
#ifdef USE_TIMER
	struct my_timer t = timer_create();
#endif
	NppiSize size = { ctx->width, ctx->height };
	Npp8u *src = NULL; // GPU-side input buffer
	uint8_t *dstbuf = NULL; // CPU-side linear output buffer (data + strides)
	uint8_t *gpudst[3] = { NULL, NULL, NULL }; // GPU-side planar output array

	// Plane dimensions
	int y_width = ctx->width;
	int uv_width = ctx->width;
	int uv_height = ctx->height;

	switch (ctx->dst_colorspace) {
		case YUV420P:
			uv_height /=  2;
			/* fall through */
		case YUV422P:
			uv_width /= 2;
			break;
		case YUV444P:
			;
		default:
			fprintf(stderr, "%s: Unimplemented destination colorspace: %d\n", __FUNCTION__, ctx->dst_colorspace);
			return 1;
	}


	// Pin CPU input buffer if possible
	if (cudaHostRegister((void *)in[0], stride[0]*ctx->height, cudaHostRegisterMapped)) {
		pinned_input_buffer = 0;
	}
		
	// Allocate GPU input buffer
	if (cudaMalloc((void *)&src, stride[0]*ctx->height)) {
		cuda_err("cudaMalloc input buf");
		goto err0;
	}
	timer_display_and_reset(&t, "cudaMalloc in");

	// Copy input data to GPU buffer
	if (pinned_input_buffer) {
		// Use asynchronous copy if the buffer is pinned
		if (cudaMemcpyAsync(src, in[0], stride[0]*ctx->height, cudaMemcpyHostToDevice, 0)) {
			cuda_err("cudaMemcpyAsync input buf");
			goto err1;
		}
	} else {
		if (cudaMemcpy(src, in[0], stride[0]*ctx->height, cudaMemcpyHostToDevice)) {
			cuda_err("cudaMemcpy input buf");
			goto err1;
		}
	}

	cudaDeviceSynchronize();
	timer_display_and_reset(&t, "cudaMemcpy in");
	

	// Allocate GPU output buffer
	cudaMallocPitch((void *)&gpudst[0], (void *)&out_stride[0], y_width, ctx->height);
	cudaMallocPitch((void *)&gpudst[1], (void *)&out_stride[1], uv_width, uv_height);
	cudaMallocPitch((void *)&gpudst[2], (void *)&out_stride[2], uv_width, uv_height);
	timer_display_and_reset(&t, "cudaMalloc out");

	// Allocate CPU output buffer
	out[0] = malloc(out_stride[0] * ctx->height + (out_stride[1] + out_stride[2]) * uv_height);
	out[1] = out[0] + out_stride[0] * ctx->height;
	out[2] = out[1] + out_stride[1] * uv_height;
	printf("instride %d\nCPU input:\t%p\n->GPU input:\t%p\noutstride %d\t%d\t%d\nCPU output:\t%p\t%p\t%p\n->GPU output:\t%p\t%p\t%p\n", stride[0], in[0], src, out_stride[0], out_stride[1], out_stride[2], out[0], out[1], out[2], gpudst[0], gpudst[1], gpudst[2]);
	
	// Pin output buffer if possible
	if (cudaHostRegister((void *)out[0], (out_stride[0] + out_stride[1] + out_stride[2]) * ctx->height, cudaHostRegisterMapped)) {
		pinned_output_buffer = 0;
	}

	packed_to_subsampled_planar_func func = NULL;
	packed_to_planar_func func2 = NULL;
	int err = 0;

	if (ctx->dst_colorspace == YUV444P) {
		func2 = get_conversion_function_444(ctx->src_colorspace, ctx->dst_colorspace);
		if (func2) 
			err = func2(src, stride[0], gpudst, out_stride[0], size);
		else goto err2;
	} else {
		func = get_conversion_function_subsampled(ctx->src_colorspace, ctx->dst_colorspace);
		if (func)
			err = func(src, stride[0], gpudst, out_stride, size);
		else goto err2;
	}

	cudaDeviceSynchronize();
	timer_display_and_reset(&t, "nppiRGBToYuv");
	if (err) {
		const char *str = NULL;
		switch (err) {
			case -4: str = "NPP_NULL_POINTER_ERROR"; break;
			case -7: str = "NPP_STEP_ERROR"; break;
			case -8: str = "NPP_ALIGNMENT_ERROR"; break;
			case -19: str = "NPP_NOT_EVEN_STEP_ERROR"; break;
			default: 
					  str = "(unknown)"; 
		}
		fprintf(stderr, "nppiRGBToYCbCr420_8u_C3P3R failed: %d - %s\n", err, str);
		goto err2;
	}

	if (pinned_output_buffer) {
		if (cudaMemcpyAsync(out[0], gpudst[0], out_stride[0] * ctx->height, cudaMemcpyDeviceToHost, 0) ||
			cudaMemcpyAsync(out[1], gpudst[1], out_stride[1] * uv_height, cudaMemcpyDeviceToHost, 0) ||
			cudaMemcpyAsync(out[2], gpudst[2], out_stride[2] * uv_height, cudaMemcpyDeviceToHost, 0)) {
			cuda_err("cudaMemcpyAsync output buf");
			goto err2;
		}
	} else {
		if (cudaMemcpy(out[0], gpudst[0], out_stride[0] * ctx->height, cudaMemcpyDeviceToHost) ||
			cudaMemcpy(out[1], gpudst[1], out_stride[1] * uv_height, cudaMemcpyDeviceToHost) ||
			cudaMemcpy(out[2], gpudst[2], out_stride[2] * uv_height, cudaMemcpyDeviceToHost)) {
			cuda_err("cudaMemcpy output buf");
			goto err2;
		}
	}
	cudaDeviceSynchronize();
	timer_display_and_reset(&t, "memcpy out");

	// Free GPU output buffer
	cudaFree(gpudst[0]);
	cudaFree(gpudst[1]);
	cudaFree(gpudst[2]);
	// Free GPU input buffer
	cudaFree(src);

	// Un-pin CPU buffers
	if (pinned_input_buffer) {
		cudaHostUnregister((void *)in);
	}
	if (pinned_output_buffer) {
		cudaHostUnregister((void *)out[0]);
	}

	timer_display_and_reset(&t, "free GPU buffers");

	return 0;

err2:
	if (pinned_output_buffer) 
		cudaHostUnregister((void *)out[0]);
	cudaFree(gpudst[0]);
	cudaFree(gpudst[1]);
	cudaFree(gpudst[2]);
	free(out[0]);
err1:
	cudaFree(src);
err0:
	if (pinned_input_buffer)
		cudaHostUnregister((void *)in);
	return 1;
}

int free_csc_image(uint8_t *buf[3])
{
	free(buf[0]);
	return 0;
}

void free_csc(struct csc_nvcuda_ctx *ctx)
{
	return;
}

const char *get_flags_description(struct csc_nvcuda_ctx *ctx) {
	return "";
}

