/* Copyright (C) 2013 Arthur Huillet
 */
#ifdef _WIN32
#include "stdint.h"
#include "inttypes.h"
#else
#include "stdint.h"
#endif

#ifdef _WIN32
#define _STDINT_H
#endif

/** Opaque structure - "context". You must have a context to convert frames */
struct csc_nvcuda_ctx;

/**
 * Initialize Cuda. Call this before doing anything else.
 * Will be called by init_csc if you forget.
 * @return 0 if OK, non zero on error
 */
int init_cuda(void);

/** Create a CSC context
 * @return NULL on error
 */
struct csc_nvcuda_ctx *init_csc(int width, int height, const char *src_format_str, const char *dst_format_str);

/** Free a CSC context */
void free_csc(struct csc_nvcuda_ctx *ctx);

/** Colorspace conversion.
 * Note: you must call free_csc_image() to free the image buffer.
 @param in: Input buffer planes.
 @param stride: Input strides.
 @param out: Array of pointers to be set to point to data planes.
 @param out_stride: Array of strides 
 @return: 0 if OK, 1 on error
*/
int csc_image(struct csc_nvcuda_ctx *ctx, const uint8_t *in[3], const int in_stride[3], uint8_t *out[3], int out_stride[3]);

/**
 * Free the output of RGB 2 YUV conversion. You have to pass the pointer to the Y plane. This function will
 * free all planes at once.
 */
int free_csc_image(uint8_t *buf[3]);

