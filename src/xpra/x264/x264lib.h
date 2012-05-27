#ifdef _WIN32
#include "stdint.h"
#include "inttypes.h"
#else
#include "stdint.h"
#endif

#ifndef _WIN32
#include <x264.h>
#else
typedef void x264_t;
#define inline __inline
#endif

/** Opaque structure - "context". You must have a context to encode images of a given size */
struct x264lib_ctx;

/** Create an encoding context for images of a given size.  */
struct x264lib_ctx *init_encoder(int width, int height);

/** Create a decoding context for images of a given size. */
struct x264lib_ctx *init_decoder(int width, int height);

/** Cleanup encoding context. Must be freed after calling this function. */
void clean_encoder(struct x264lib_ctx *);

/** Cleanup decoding context. Must be freed after calling this function. */
void clean_decoder(struct x264lib_ctx *);

/** Colourspace conversion.
 * Note: you must call compress_image to free the image buffer.
 @param in: Input buffer, format is packed RGB24.
 @param stride: Input stride (size is taken from context).
 @return: the converted picture.
*/
x264_picture_t* csc_image(struct x264lib_ctx *ctx, const uint8_t *in, int stride);

/** Compress an image using the given context.
 @param pic_in: the input image, as returned by csc_image
 @param out: Will be set to point to the output data. This output buffer MUST NOT BE FREED and will be erased on the
 next call to compress_image.
 @param outsz: Output size
*/
int compress_image(struct x264lib_ctx *ctx, x264_picture_t *pic_in, uint8_t **out, int *outsz);

/** Decompress an image using the given context.
 @param in: Input buffer, format is H264.
 @param size: Input size.
 @param out: Will be set to point to the output data in RGB24 format.
 @param outstride: Output stride.
*/
int decompress_image(struct x264lib_ctx *, uint8_t *in, int size, uint8_t **out, int *outsize, int *outstride);

/**
 * Change the speed of encoding (x264 preset).
 * @param increase: increase encoding speed (decrease preset) by this value. Negative values decrease encoding speed.
 */
void change_encoding_speed(struct x264lib_ctx *ctx, int increase);
